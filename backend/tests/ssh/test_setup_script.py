"""megoo-setup.sh, run as root in the fake server on scratch accounts: what it changes, what it checks, and what it
refuses before changing anything."""

from uuid import uuid4

import pytest

from app.ssh import hostkeys, keys

FROM = "192.0.2.10,10.0.0.0/8"
CTL = "/usr/local/sbin/megoo-ctl"


@pytest.fixture(scope="module")
def key() -> str:
    keys.ensure_key()
    return keys.public_key()


@pytest.fixture
def scratch(fake_server):
    """A fresh account name, removed afterwards with its sudo rule."""
    name = f"megoo-t{uuid4().hex[:8]}"
    yield name
    fake_server.exec("userdel", "-r", name)
    fake_server.exec("rm", "-f", f"/etc/sudoers.d/megoo-ctl-{name}")


def files(name: str) -> list[str]:
    return [CTL, f"/etc/sudoers.d/megoo-ctl-{name}", f"/home/{name}/.ssh/authorized_keys", f"/home/{name}/.ssh"]


def prepare(fake_server, name: str, key: str):
    return fake_server.setup("--user", name, "--from", FROM, "--key", key)


def owner_and_mode(fake_server, path: str) -> str:
    return fake_server.exec("stat", "-c", "%U %a", path).stdout.strip()


def test_a_first_run_prepares_everything_and_check_passes(fake_server, scratch, key):
    result = prepare(fake_server, scratch, key)

    assert result.returncode == 0, result.stdout + result.stderr
    for line in (
        f"Created the account {scratch}.",
        f"Added {scratch} to systemd-journal.",
        f"Added {scratch} to adm.",
        f"Wrote /etc/sudoers.d/megoo-ctl-{scratch}.",
        f"Wrote /home/{scratch}/.ssh/authorized_keys.",
        "The server is ready.",
    ):
        assert line in result.stdout
    keyfile = fake_server.exec("cat", f"/home/{scratch}/.ssh/authorized_keys").stdout
    assert keyfile == f'from="{FROM}" {key}\n'
    assert owner_and_mode(fake_server, CTL) == "root 755"
    assert owner_and_mode(fake_server, f"/etc/sudoers.d/megoo-ctl-{scratch}") == "root 440"
    assert owner_and_mode(fake_server, f"/home/{scratch}/.ssh/authorized_keys") == f"{scratch} 600"
    assert owner_and_mode(fake_server, f"/home/{scratch}/.ssh") == f"{scratch} 700"

    check = fake_server.setup("--check", "--user", scratch)

    assert check.returncode == 0, check.stdout + check.stderr
    assert "[FAIL]" not in check.stdout
    assert hostkeys.fingerprint(key) in check.stdout
    assert FROM in check.stdout


def test_a_second_run_changes_no_file(fake_server, scratch, key):
    def stats() -> str:
        return fake_server.exec("stat", "-c", "%n %i %Y %a %U", *files(scratch)).stdout

    assert prepare(fake_server, scratch, key).returncode == 0
    before = stats()

    again = prepare(fake_server, scratch, key)

    assert again.returncode == 0, again.stdout + again.stderr
    assert "Nothing to change." in again.stdout
    assert stats() == before


def test_a_missing_group_fails_check_and_a_new_run_repairs_it(fake_server, scratch, key):
    assert prepare(fake_server, scratch, key).returncode == 0
    fake_server.exec("gpasswd", "-d", scratch, "adm")

    check = fake_server.setup("--check", "--user", scratch)

    assert check.returncode == 1
    assert f"[FAIL] {scratch} is not in adm." in check.stdout
    assert "1 check(s) failed." in check.stdout

    repaired = prepare(fake_server, scratch, key)

    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert f"Added {scratch} to adm." in repaired.stdout


def test_it_leaves_docker(fake_server, scratch, key):
    assert fake_server.exec("useradd", "-m", "-G", "docker", scratch).returncode == 0

    result = prepare(fake_server, scratch, key)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Removed {scratch} from the docker group" in result.stdout
    assert "docker" not in fake_server.exec("id", "-Gn", scratch).stdout.split()


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--key", "not a key"),
        ("--key", 'ssh-ed25519 AAAA" x'),
        ("--from", '1.2.3.4" command="id'),
        ("--from", "1.2.3.4 5.6.7.8"),
        ("--from", "<platform-address>"),
        ("--from", None),
        ("--user", "root"),
        ("--user", "Bad;name"),
    ],
)
def test_bad_input_stops_before_any_change(fake_server, scratch, key, option, value):
    given = {"--user": scratch, "--from": FROM, "--key": key, option: value}
    args = [part for name, given_value in given.items() if given_value is not None for part in (name, given_value)]

    result = fake_server.setup(*args)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "Nothing was changed." in result.stderr
    assert fake_server.exec("getent", "passwd", scratch).returncode != 0
    assert fake_server.exec("test", "-e", "/etc/sudoers.d/megoo-ctl-root").returncode != 0


def test_a_uid_0_account_is_refused(fake_server, key):
    result = fake_server.setup("--user", "megoo-root", "--from", FROM, "--key", key)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "Nothing was changed." in result.stderr


def test_an_invalid_sudoers_file_is_not_installed(fake_server, scratch, key):
    stub = fake_server.exec(
        "sh", "-c", "printf '#!/bin/sh\\nexit 1\\n' > /usr/local/sbin/visudo && chmod 0755 /usr/local/sbin/visudo"
    )
    assert stub.returncode == 0, stub.stderr
    try:
        result = prepare(fake_server, scratch, key)
    finally:
        fake_server.exec("rm", "-f", "/usr/local/sbin/visudo")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "was not installed" in result.stderr
    assert fake_server.exec("test", "-e", f"/etc/sudoers.d/megoo-ctl-{scratch}").returncode != 0
    leftovers = fake_server.exec("sh", "-c", "ls -A /etc/sudoers.d | grep '^\\.megoo-ctl\\.' || true")
    assert leftovers.stdout == ""


def test_check_of_a_missing_account_fails(fake_server, scratch):
    result = fake_server.setup("--check", "--user", scratch)

    assert result.returncode == 1
    assert f"[FAIL] The account {scratch} does not exist." in result.stdout


@pytest.fixture
def victim(fake_server):
    """A root-owned directory holding a root-owned file, which the account must never get through a symlink."""
    path = f"/var/tmp/victim-{uuid4().hex[:8]}"
    made = fake_server.exec("sh", "-c", f"install -d -m 0755 {path} && install -m 0644 /dev/null {path}/file")
    assert made.returncode == 0, made.stderr
    yield path
    fake_server.exec("rm", "-rf", path)


@pytest.mark.parametrize(
    ("link", "target"),
    [(".ssh", ""), (".ssh/authorized_keys", "/file")],
)
def test_a_symlink_in_the_accounts_ssh_directory_is_refused(fake_server, scratch, key, victim, link, target):
    assert prepare(fake_server, scratch, key).returncode == 0
    home = f"/home/{scratch}"
    swapped = fake_server.exec("sh", "-c", f"rm -rf {home}/{link} && ln -s {victim}{target} {home}/{link}", user=scratch)
    assert swapped.returncode == 0, swapped.stderr

    result = prepare(fake_server, scratch, key)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "is a symbolic link" in result.stderr
    assert "Nothing was changed." in result.stderr
    assert owner_and_mode(fake_server, victim) == "root 755"
    assert owner_and_mode(fake_server, f"{victim}/file") == "root 644"
    assert fake_server.exec("cat", f"{victim}/file").stdout == ""

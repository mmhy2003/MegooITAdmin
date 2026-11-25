import json
import socket

from app.ssh.client import account_of, connect
from app.ssh.keys import public_key


def banner(host: str, port: int) -> str:
    with socket.create_connection((host, port), timeout=10) as sock:
        return sock.recv(256).decode(errors="replace")


def test_the_fake_server_answers_with_openssh(fake_server):
    assert banner(fake_server.host, fake_server.port).startswith("SSH-2.0-OpenSSH")


def test_swap_host_key_gives_new_keys_and_sshd_keeps_answering(fake_server):
    before = fake_server.host_key()

    fake_server.swap_host_key()

    after = fake_server.host_key()
    assert after != before
    assert after.startswith("ssh-ed25519 ")
    assert banner(fake_server.host, fake_server.port).startswith("SSH-2.0-OpenSSH")


async def test_the_host_keys_survive_a_restart(fake_server):
    before = fake_server.host_key()

    fake_server.restart()

    assert fake_server.host_key() == before
    async with connect(fake_server.host, fake_server.port, "megoo", before) as conn:
        uid, _ = await account_of(conn)
    assert uid != 0


FROM = "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1,fc00::/7"


def test_the_platform_key_is_authorized_for_every_account(fake_server):
    key = " ".join(public_key().split()[:2])
    for user in ("megoo", "megoo-nologs", "megoo-nosudo", "megoo-wide"):
        result = fake_server.exec("cat", f"/home/{user}/.ssh/authorized_keys")
        assert result.returncode == 0, result.stderr
        assert len(result.stdout.splitlines()) == 1, user
        assert result.stdout.startswith(f'from="{FROM}" {key}'), user
    for user in ("megoo-docker", "megoo-root"):
        result = fake_server.exec("cat", f"/home/{user}/.ssh/authorized_keys")
        assert result.returncode == 0, result.stderr
        assert result.stdout.split()[:2] == key.split(), user


def test_the_accounts_are_what_the_checks_expect(fake_server):
    assert fake_server.exec("id", "-u", "megoo-root").stdout.strip() == "0"
    assert "docker" in fake_server.exec("id", "-Gn", "megoo-docker").stdout.split()
    megoo = fake_server.exec("id", "-Gn", "megoo").stdout.split()
    assert "docker" not in megoo
    assert {"systemd-journal", "adm"} <= set(megoo)
    assert fake_server.exec("id", "-u", "megoo").stdout.strip() != "0"
    nologs = fake_server.exec("id", "-Gn", "megoo-nologs").stdout.split()
    assert "systemd-journal" in nologs
    assert "adm" not in nologs
    assert fake_server.exec("test", "-e", "/etc/sudoers.d/megoo-ctl-megoo-nosudo").returncode != 0
    assert fake_server.exec("test", "-f", "/etc/sudoers.d/megoo-wide-all").returncode == 0
    check = fake_server.setup("--check", "--user", "megoo")
    assert check.returncode == 0, check.stdout + check.stderr


def test_the_stub_tools_print_their_default_fixtures(fake_server):
    units = fake_server.exec("systemctl", "list-units", "--type=service", user="megoo")
    assert units.returncode == 0, units.stderr
    assert any(line.startswith("nginx.service loaded failed failed") for line in units.stdout.splitlines())
    ps = fake_server.ctl("docker", "ps")
    assert ps.returncode == 0, ps.stderr
    lines = ps.stdout.splitlines()
    assert len(lines) == 4
    assert [json.loads(line)["Names"] for line in lines] == [
        "shop-web-1",
        "shop-db-1",
        "monitoring-grafana-1",
        "hello-adhoc",
    ]


def test_a_fixture_sets_output_and_exit_status_and_is_put_back(fake_server):
    with fake_server.fixture("journalctl", "line\n", exit=3):
        inside = fake_server.exec("journalctl", "-q", user="megoo")
        assert (inside.stdout, inside.returncode) == ("line\n", 3)
    after = fake_server.exec("journalctl", "-q", user="megoo")
    assert (after.stdout, after.returncode) == ("", 0)

    with fake_server.fixture("docker_ps", ""):
        assert fake_server.ctl("docker", "ps").stdout == ""
    assert len(fake_server.ctl("docker", "ps").stdout.splitlines()) == 4


def test_stub_calls_by_megoo_are_logged(fake_server):
    fake_server.clear_tool_log()

    result = fake_server.exec("apt-get", "-s", "upgrade", user="megoo")

    assert result.returncode == 0, result.stderr
    assert fake_server.tool_log() == ["apt-get [-s] [upgrade]"]


def test_openssl_is_installed(fake_server):
    assert fake_server.exec("openssl", "version", user="megoo").returncode == 0


def test_hidden_hides_a_tool(fake_server):
    probe = ("sh", "-c", "command -v journalctl")
    with fake_server.hidden("/usr/local/bin/journalctl"):
        assert fake_server.exec(*probe, user="megoo").returncode != 0
    assert fake_server.exec(*probe, user="megoo").returncode == 0

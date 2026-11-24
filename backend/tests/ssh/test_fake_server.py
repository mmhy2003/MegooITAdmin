import socket

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


def test_the_platform_key_is_authorized_for_the_three_accounts(fake_server):
    expected = public_key().split()[:2]
    for user in ("megoo", "megoo-docker", "megoo-root"):
        result = fake_server.exec("cat", f"/home/{user}/.ssh/authorized_keys")
        assert result.returncode == 0, result.stderr
        assert result.stdout.split()[:2] == expected, user


def test_the_accounts_are_what_the_checks_expect(fake_server):
    assert fake_server.exec("id", "-u", "megoo-root").stdout.strip() == "0"
    assert "docker" in fake_server.exec("id", "-Gn", "megoo-docker").stdout.split()
    assert "docker" not in fake_server.exec("id", "-Gn", "megoo").stdout.split()
    assert fake_server.exec("id", "-u", "megoo").stdout.strip() != "0"

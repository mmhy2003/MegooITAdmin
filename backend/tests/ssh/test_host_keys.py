import asyncssh
import pytest

from app.ssh.hostkeys import InvalidHostKey, fingerprint, key_type, openssh_line, parse


@pytest.fixture(scope="module")
def key() -> asyncssh.SSHKey:
    return asyncssh.generate_private_key("ssh-ed25519")


def test_the_fingerprint_is_the_sha256_one(key):
    line = openssh_line(key)
    assert fingerprint(line) == key.get_fingerprint("sha256")
    assert fingerprint(line).startswith("SHA256:")


def test_the_key_type_is_read_from_the_line(key):
    assert key_type(openssh_line(key)) == "ssh-ed25519"


def test_the_line_has_no_comment(key):
    assert len(openssh_line(key).split()) == 2


def test_a_comment_does_not_change_the_fingerprint(key):
    line = openssh_line(key)
    assert fingerprint(f"{line} root@server\n") == fingerprint(line)


@pytest.mark.parametrize("line", ["not a key", "ssh-ed25519 AAAA"])
def test_a_line_that_is_not_a_key_is_refused(line):
    with pytest.raises(InvalidHostKey):
        parse(line)

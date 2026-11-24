"""Host keys as OpenSSH lines ("ssh-ed25519 AAAA…"), their SHA256 fingerprints and their types."""

import asyncssh


class InvalidHostKey(ValueError):
    """The line is not an OpenSSH public key."""


def parse(line: str) -> asyncssh.SSHKey:
    try:
        return asyncssh.import_public_key(line.strip())
    except Exception as error:
        raise InvalidHostKey(f"Not an SSH public key: {error}") from error


def openssh_line(key: asyncssh.SSHKey) -> str:
    """The key's type and data, without a comment."""
    return " ".join(key.export_public_key("openssh").decode().split()[:2])


def fingerprint(line: str) -> str:
    """"SHA256:…", as ssh-keygen -lf shows it."""
    return parse(line).get_fingerprint("sha256")


def key_type(line: str) -> str:
    algorithm = parse(line).get_algorithm()
    return algorithm.decode() if isinstance(algorithm, bytes) else algorithm

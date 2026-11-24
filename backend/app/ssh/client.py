"""The only module that opens SSH connections: a host key fetch for pinning, and a sign-in that trusts the pinned
host key and nothing else, and what the signed-in account may do with sudo."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import asyncssh

from app.ssh import hostkeys
from app.ssh.keys import load_key

CONNECT_TIMEOUT = 10  # seconds: TCP and key exchange
LOGIN_TIMEOUT = 10  # seconds: sign-in
COMMAND_TIMEOUT = 5  # seconds: the account check
# What a fetch accepts, best first. No "ssh-rsa" (SHA-1): such servers fail with ssh_error.
HOST_KEY_ALGS = [
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "rsa-sha2-512",
    "rsa-sha2-256",
]
CTL = "/usr/local/sbin/megoo-ctl"
_SUDO_HEADER = re.compile(r"^User \S+ may run the following commands on ")
_RUNAS = re.compile(r"^\([^)]*\)\s*")
_TAGS = re.compile(r"^(?:[A-Z_]+:\s*)+")


# A signed-in connection, the type other modules name so that only this one uses asyncssh's connection API.
Connection = asyncssh.SSHClientConnection


class SshFailure(Exception):
    reason = "ssh_error"


class Unreachable(SshFailure):
    reason = "unreachable"


class KeyRefused(SshFailure):
    reason = "key_refused"


class SshError(SshFailure):
    reason = "ssh_error"


class AccountCheckFailed(SshFailure):
    reason = "account_check_failed"


class HostKeyChanged(SshFailure):
    reason = "host_key_changed"

    def __init__(self, presented: str | None) -> None:
        """`presented` is the key the server presented as an OpenSSH line, or None when it could not be read."""
        super().__init__("the server presented another host key")
        self.presented = presented


class _PinnedClient(asyncssh.SSHClient):
    """Remembers the key a server presented when it was not the pinned one; trusts nothing else."""

    def __init__(self) -> None:
        self.presented: asyncssh.SSHKey | None = None

    def validate_host_public_key(self, host: str, addr: str, port: int, key: asyncssh.SSHKey) -> bool:
        self.presented = key
        return False


async def fetch_host_key(address: str, port: int) -> str:
    """The server's host key as an OpenSSH line: key exchange only, no sign-in."""
    try:
        # get_server_host_key takes its connect timeout from the options only.
        options = asyncssh.SSHClientConnectionOptions(config=None, connect_timeout=CONNECT_TIMEOUT)
        key = await asyncssh.get_server_host_key(
            address, port, server_host_key_algs=HOST_KEY_ALGS, config=None, options=options
        )
    except (OSError, TimeoutError) as error:
        raise Unreachable() from error
    except asyncssh.Error as error:
        raise SshError() from error
    if key is None:
        raise SshError()
    return hostkeys.openssh_line(key)


@asynccontextmanager
async def connect(address: str, port: int, username: str, pinned: str) -> AsyncIterator[asyncssh.SSHClientConnection]:
    """Signs in as `username` with the platform's key, only if the server presents the `pinned` host key."""
    pinned_key = hostkeys.parse(pinned)
    client_key = load_key()  # before the try: a missing key file is a 500, not "unreachable"
    client = _PinnedClient()
    try:
        conn = await asyncssh.connect(
            address,
            port,
            username=username,
            client_keys=[client_key],
            # The pinned key is the only trusted key; asyncssh then offers only its algorithms.
            known_hosts=([pinned_key], [], []),
            client_factory=lambda: client,
            agent_path=None,
            preferred_auth="publickey",
            password=None,
            config=None,
            connect_timeout=CONNECT_TIMEOUT,
            login_timeout=LOGIN_TIMEOUT,
        )
    # The order matters: HostKeyNotVerifiable and PermissionDenied are asyncssh.Errors.
    except asyncssh.HostKeyNotVerifiable as error:
        presented = None if client.presented is None else hostkeys.openssh_line(client.presented)
        raise HostKeyChanged(presented) from error
    except asyncssh.PermissionDenied as error:
        raise KeyRefused() from error
    except (OSError, TimeoutError) as error:
        raise Unreachable() from error
    except asyncssh.Error as error:
        raise SshError() from error
    async with conn:
        yield conn


async def account_of(conn: asyncssh.SSHClientConnection) -> tuple[int, list[str]]:
    """The signed-in account's uid and group names, from `id -u; id -Gn`."""
    try:
        result = await conn.run("id -u; id -Gn", check=True, timeout=COMMAND_TIMEOUT)
        uid, groups = str(result.stdout).splitlines()
        return int(uid), groups.split()
    except (asyncssh.Error, TimeoutError, ValueError) as error:
        raise AccountCheckFailed() from error


@dataclass(frozen=True)
class Setup:
    """What the setup script left on the server, as the signed-in account sees it."""

    version: int | None  # megoo-ctl's version through sudo; None when it did not answer
    limited: bool | None  # True: sudo allows only megoo-ctl; False: it allows more; None: the list could not be read


def sudo_commands(text: str) -> list[str] | None:
    """The commands of `sudo -l` (LC_ALL=C), or None when the text is not that list."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _SUDO_HEADER.match(line)), None)
    if start is None:
        return None
    commands: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            continue
        if not line[0].isspace():
            break
        entry = _TAGS.sub("", _RUNAS.sub("", line.strip()))
        commands += [command.strip() for command in entry.split(",") if command.strip()]
    return commands


async def setup_of(conn: asyncssh.SSHClientConnection) -> Setup:
    """megoo-ctl's version and whether sudo allows the account only megoo-ctl. Only an integer and a yes/no leave
    this function: what the server printed never reaches a response or an event."""
    try:
        version = await conn.run(f"sudo -n {CTL} version", timeout=COMMAND_TIMEOUT)
        listed = await conn.run("LC_ALL=C sudo -n -l", timeout=COMMAND_TIMEOUT)
    except (asyncssh.Error, TimeoutError) as error:
        raise AccountCheckFailed() from error
    found = re.fullmatch(r"megoo-ctl (\d{1,6})", str(version.stdout).strip()) if version.exit_status == 0 else None
    commands = sudo_commands(str(listed.stdout)) if listed.exit_status == 0 else None
    limited = None if not commands else all(command == CTL for command in commands)
    return Setup(version=int(found.group(1)) if found else None, limited=limited)

"""The only module that opens SSH connections: a host key fetch for pinning, and a sign-in that trusts the pinned
host key and nothing else."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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

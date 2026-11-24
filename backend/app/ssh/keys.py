"""The platform's SSH private key: one Ed25519 key in a 0600 file, made at the first start (Phase 3 moves it into
the vault)."""

import os
import stat
from pathlib import Path

import asyncssh

from app.core.config import get_settings

KEY_COMMENT = "megooitadmin"


class KeyFileError(RuntimeError):
    """The key file is missing, not a file, or readable by others."""


def key_path() -> Path:
    return Path(get_settings().ssh_key_file)


def ensure_key(path: Path | None = None) -> bool:
    """Creates the key once, readable by its owner only. Returns True when it made the key; an existing file is
    checked and kept."""
    path = path or key_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _check_file(path)
        return False
    key = asyncssh.generate_private_key("ssh-ed25519", comment=KEY_COMMENT)
    with os.fdopen(fd, "wb") as file:
        file.write(key.export_private_key("openssh"))
    return True


def _check_file(path: Path) -> None:
    status = path.stat()
    if not stat.S_ISREG(status.st_mode):
        raise KeyFileError(f"{path} is not a file")
    mode = stat.S_IMODE(status.st_mode)
    if mode & 0o077:
        raise KeyFileError(
            f"The platform's SSH key {path} is readable by others (mode {mode:o}). Run chmod 600 on it."
        )


def load_key(path: Path | None = None) -> asyncssh.SSHKey:
    path = path or key_path()
    if not path.exists():
        raise KeyFileError(
            f"The platform's SSH key {path} is missing. Restart the backend to make a new one, then put its public "
            "key on every server."
        )
    _check_file(path)
    return asyncssh.read_private_key(path)


def public_key(path: Path | None = None) -> str:
    """The public key as one authorized_keys line: "ssh-ed25519 AAAA… megooitadmin"."""
    return load_key(path).export_public_key("openssh").decode().strip()

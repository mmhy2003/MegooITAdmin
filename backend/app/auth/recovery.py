"""One-time recovery codes: 80 random bits shown as XXXX-XXXX-XXXX-XXXX and stored only as a SHA-256 hash."""

import base64
import hashlib
import os

RECOVERY_CODE_COUNT = 10
CODE_PATTERN = r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}"


def new_code() -> str:
    plain = base64.b32encode(os.urandom(10)).decode()
    return "-".join(plain[i : i + 4] for i in range(0, 16, 4))


def normalise_code(text: str) -> str:
    """Upper case, with dashes and whitespace removed."""
    return "".join(text.split()).replace("-", "").upper()


def hash_code(text: str) -> bytes:
    return hashlib.sha256(normalise_code(text).encode()).digest()

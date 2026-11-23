"""Passwords: Argon2id hashes made off the event loop, and the length rule."""

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

PASSWORD_MIN = 12
PASSWORD_MAX = 128

# The library defaults are Argon2id with its recommended parameters.
_hasher = PasswordHasher()
_dummy_hash: str | None = None


class PasswordRuleError(ValueError):
    pass


def check_rule(password: str) -> None:
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise PasswordRuleError("A password has 12 to 128 characters.")


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def verify_password(password_hash: str, password: str) -> bool:
    return await asyncio.to_thread(_verify, password_hash, password)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


async def verify_dummy(password: str) -> None:
    """Spend the time of a real check, so an unknown email answers as slowly as a known one."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password("an unused dummy password")
    await verify_password(_dummy_hash, password)

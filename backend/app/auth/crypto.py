"""TOTP secrets encrypted with AES-256-GCM under AUTH_SECRET_KEY, bound to the user's ID.

A blob is a 12-byte random nonce followed by the ciphertext and its tag. The user's ID is the associated
data, so a blob copied to another account does not decrypt.
"""

import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


class SecretUndecryptable(Exception):
    """The blob was not made with this key for this user, or it is damaged."""


def encrypt_secret(key: bytes, user_id: UUID, secret: str) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    return nonce + AESGCM(key).encrypt(nonce, secret.encode(), user_id.bytes)


def decrypt_secret(key: bytes, user_id: UUID, blob: bytes) -> str:
    if len(blob) <= NONCE_SIZE:
        raise SecretUndecryptable
    try:
        plain = AESGCM(key).decrypt(blob[:NONCE_SIZE], blob[NONCE_SIZE:], user_id.bytes)
    except InvalidTag:
        raise SecretUndecryptable from None
    return plain.decode()

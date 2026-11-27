"""Channel secrets (an SMTP password, a webhook URL, a Telegram bot token) encrypted with AES-256-GCM.

The key is derived from AUTH_SECRET_KEY with HKDF, so it is never the key of the authenticator secrets. A blob is a
12-byte random nonce followed by the ciphertext and its tag. The row it belongs to (a channel's ID, or EMAIL_ROW) is
the associated data, so a blob copied to another row does not decrypt.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.auth.crypto import SecretUndecryptable
from app.core.config import get_settings

NONCE_SIZE = 12
EMAIL_ROW = b"notification_email"
_INFO = b"megooitadmin notification secrets"


def notification_key() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(get_settings().auth_key())


def seal(plain: str, bound_to: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    return nonce + AESGCM(notification_key()).encrypt(nonce, plain.encode(), bound_to)


def unseal(blob: bytes, bound_to: bytes) -> str:
    if len(blob) <= NONCE_SIZE:
        raise SecretUndecryptable
    try:
        plain = AESGCM(notification_key()).decrypt(blob[:NONCE_SIZE], blob[NONCE_SIZE:], bound_to)
    except InvalidTag:
        raise SecretUndecryptable from None
    return plain.decode()

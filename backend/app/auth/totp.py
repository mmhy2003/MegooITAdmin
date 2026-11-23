"""TOTP codes (6 digits, 30 seconds, SHA-1) with one step of drift and no replay of a used step."""

import hmac
from datetime import datetime

import pyotp

ISSUER = "MegooITAdmin"
PERIOD = 30


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def verify(secret: str, code: str, last_step: int | None, at: datetime) -> int | None:
    """Return the step the code belongs to, or None. Steps up to last_step were used already."""
    code = code.replace(" ", "")
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current = int(at.timestamp()) // PERIOD
    totp = pyotp.TOTP(secret)
    for step in (current - 1, current, current + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None

import base64
from datetime import UTC, datetime

import pyotp
import pytest

from app.auth.totp import PERIOD, new_secret, provisioning_uri, verify

# The RFC 6238 SHA-1 seed "12345678901234567890" in base32.
SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
AT = datetime.fromtimestamp(1111111111, UTC)
STEP = 1111111111 // PERIOD


def at(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)


def code_for(step: int) -> str:
    return pyotp.TOTP(SECRET).generate_otp(step)


@pytest.mark.parametrize(
    ("timestamp", "code"),
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ],
)
def test_the_rfc_6238_vectors_match(timestamp, code):
    assert verify(SECRET, code, None, at(timestamp)) == timestamp // 30


def test_one_step_of_drift_either_way_is_accepted():
    assert verify(SECRET, code_for(STEP - 1), None, AT) == STEP - 1
    assert verify(SECRET, code_for(STEP + 1), None, AT) == STEP + 1


def test_two_steps_of_drift_are_refused():
    assert verify(SECRET, code_for(STEP - 2), None, AT) is None
    assert verify(SECRET, code_for(STEP + 2), None, AT) is None


def test_a_used_step_and_an_earlier_one_are_refused():
    assert verify(SECRET, code_for(STEP), STEP, AT) is None
    assert verify(SECRET, code_for(STEP - 1), STEP, AT) is None
    assert verify(SECRET, code_for(STEP + 1), STEP, AT) == STEP + 1


def test_spaces_are_ignored_and_letters_refused():
    assert verify(SECRET, "050 471", None, AT) == STEP
    assert verify(SECRET, " 05 04 71 ", None, AT) == STEP
    assert verify(SECRET, "05O471", None, AT) is None
    assert verify(SECRET, "05047", None, AT) is None
    assert verify(SECRET, "0504711", None, AT) is None
    assert verify(SECRET, "", None, AT) is None


def test_the_uri_names_the_issuer_and_the_email():
    uri = provisioning_uri(SECRET, "owner@example.com")

    assert uri.startswith("otpauth://totp/MegooITAdmin:owner%40example.com?secret=")
    assert "issuer=MegooITAdmin" in uri


def test_a_new_secret_is_32_base32_characters():
    secret = new_secret()

    assert len(secret) == 32
    base64.b32decode(secret)
    assert new_secret() != secret

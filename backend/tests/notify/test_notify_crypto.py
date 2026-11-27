from uuid import uuid4

import pytest

from app.auth.crypto import SecretUndecryptable
from app.core.config import get_settings
from app.notify.crypto import EMAIL_ROW, notification_key, seal, unseal


def test_a_secret_round_trips():
    row = uuid4().bytes
    blob = seal('{"url": "https://hooks.example.com/abc"}', row)
    assert b"hooks.example.com" not in blob
    assert unseal(blob, row) == '{"url": "https://hooks.example.com/abc"}'
    assert unseal(seal("smtp-password", EMAIL_ROW), EMAIL_ROW) == "smtp-password"


def test_a_blob_moved_to_another_row_does_not_open():
    blob = seal("secret", uuid4().bytes)
    with pytest.raises(SecretUndecryptable):
        unseal(blob, uuid4().bytes)
    with pytest.raises(SecretUndecryptable):
        unseal(blob, EMAIL_ROW)


def test_the_key_is_not_the_auth_key():
    key = notification_key()
    assert len(key) == 32
    assert key != get_settings().auth_key()


def test_a_short_blob_does_not_open():
    with pytest.raises(SecretUndecryptable):
        unseal(b"\x00" * 12, EMAIL_ROW)

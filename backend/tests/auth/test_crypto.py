from uuid import uuid4

import pytest

from app.auth.crypto import SecretUndecryptable, decrypt_secret, encrypt_secret

KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def test_a_secret_round_trips():
    user_id = uuid4()
    blob = encrypt_secret(KEY, user_id, SECRET)
    assert decrypt_secret(KEY, user_id, blob) == SECRET


def test_another_users_id_does_not_decrypt():
    blob = encrypt_secret(KEY, uuid4(), SECRET)
    with pytest.raises(SecretUndecryptable):
        decrypt_secret(KEY, uuid4(), blob)


def test_a_changed_key_does_not_decrypt():
    user_id = uuid4()
    blob = encrypt_secret(KEY, user_id, SECRET)
    other_key = bytes(reversed(KEY))
    with pytest.raises(SecretUndecryptable):
        decrypt_secret(other_key, user_id, blob)


def test_two_encryptions_differ():
    user_id = uuid4()
    assert encrypt_secret(KEY, user_id, SECRET) != encrypt_secret(KEY, user_id, SECRET)


@pytest.mark.parametrize("length", [0, 12, 20])
def test_a_truncated_blob_does_not_decrypt(length):
    user_id = uuid4()
    blob = encrypt_secret(KEY, user_id, SECRET)
    with pytest.raises(SecretUndecryptable):
        decrypt_secret(KEY, user_id, blob[:length])


def test_the_ciphertext_does_not_hold_the_secret():
    blob = encrypt_secret(KEY, uuid4(), SECRET)
    assert SECRET.encode() not in blob

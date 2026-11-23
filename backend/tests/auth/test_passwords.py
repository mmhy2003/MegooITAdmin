import argon2
import pytest

from app.auth.passwords import (
    PasswordRuleError,
    check_rule,
    hash_password,
    needs_rehash,
    verify_dummy,
    verify_password,
)


async def test_a_hash_verifies_and_a_wrong_password_does_not():
    password_hash = await hash_password("correct horse battery")

    assert await verify_password(password_hash, "correct horse battery") is True
    assert await verify_password(password_hash, "correct horse battery!") is False


async def test_the_hash_is_argon2id():
    assert (await hash_password("correct horse battery")).startswith("$argon2id$")


def test_the_rule_refuses_11_and_129_characters_and_accepts_12_and_128():
    for length in (11, 129):
        with pytest.raises(PasswordRuleError, match="A password has 12 to 128 characters."):
            check_rule("x" * length)

    check_rule("x" * 12)
    check_rule("x" * 128)


async def test_an_old_parameter_hash_needs_a_rehash():
    old = argon2.PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("correct horse battery")

    assert needs_rehash(old) is True
    assert needs_rehash(await hash_password("correct horse battery")) is False


async def test_verify_returns_false_for_a_malformed_hash():
    assert await verify_password("not a hash", "correct horse battery") is False
    assert await verify_password("$argon2id$v=19$m=65536,t=3,p=4$broken", "correct horse battery") is False


async def test_verify_dummy_runs_without_error():
    assert await verify_dummy("correct horse battery") is None
    assert await verify_dummy("another password") is None

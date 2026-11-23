import base64
import hashlib
import re

from app.auth.recovery import CODE_PATTERN, hash_code, new_code, normalise_code


def test_a_code_has_the_shown_format_and_80_bits():
    code = new_code()
    assert re.fullmatch(CODE_PATTERN, code)
    plain = code.replace("-", "")
    assert len(plain) == 16
    assert len(base64.b32decode(plain)) == 10


def test_codes_differ():
    assert len({new_code() for _ in range(50)}) == 50


def test_normalise_ignores_case_dashes_and_spaces():
    assert normalise_code(" abcd-EFGH ijkl\tmnop\n") == "ABCDEFGHIJKLMNOP"


def test_the_hash_is_sha256_of_the_normalised_code():
    digest = hash_code("abcd-efgh-ijkl-mnop")
    assert digest == hashlib.sha256(b"ABCDEFGHIJKLMNOP").digest()
    assert len(digest) == 32
    assert hash_code("ABCDEFGHIJKLMNOP") == digest

import re

from auth_helpers import events, make_user, put_setup_code
from sqlalchemy import select

from app.auth import cli
from app.auth.models import SetupCode
from app.auth.recovery import CODE_PATTERN, hash_code
from app.core.db import SessionLocal

SETUP_CODE = re.compile("Setup code: (" + CODE_PATTERN + ")")


async def stored_hashes() -> list[bytes]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(SetupCode.code_hash))).all())


async def test_setup_code_prints_a_code_that_setup_accepts(clean_auth, clock, capsys):
    assert await cli.create_setup_code(if_no_account=False) == 0
    out = capsys.readouterr().out
    match = SETUP_CODE.search(out)
    assert match
    assert "Enter it on the setup page of MegooITAdmin. It works until the Owner account exists." in out
    assert await stored_hashes() == [hash_code(match.group(1))]
    (event,) = await events("auth.setup_code_created")
    assert (event.actor_type, event.actor_name, event.result) == ("system", "cli", "success")


async def test_a_new_setup_code_replaces_the_old_one(clean_auth, clock, capsys):
    await put_setup_code("ABCD-EFGH-IJKL-MNOP", failed_attempts=3)
    assert await cli.create_setup_code(if_no_account=False) == 0
    code = SETUP_CODE.search(capsys.readouterr().out).group(1)
    async with SessionLocal() as session:
        (row,) = (await session.scalars(select(SetupCode))).all()
    assert (row.code_hash, row.failed_attempts) == (hash_code(code), 0)


async def test_setup_code_refuses_once_an_account_exists(clean_auth, clock, capsys):
    await make_user()
    assert await cli.create_setup_code(if_no_account=False) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "An account exists already, so setup is closed.\n"
    assert await stored_hashes() == []
    assert await events("auth.setup_code_created") == []


async def test_if_no_account_is_silent_once_an_account_exists(clean_auth, clock, capsys):
    await make_user()
    assert await cli.create_setup_code(if_no_account=True) == 0
    assert capsys.readouterr() == ("", "")
    assert await stored_hashes() == []
    assert await events("auth.setup_code_created") == []


def test_main_passes_the_flag(monkeypatch):
    calls = []

    async def fake(*, if_no_account: bool) -> int:
        calls.append(if_no_account)
        return 7

    monkeypatch.setattr(cli, "create_setup_code", fake)
    assert cli.main(["setup-code", "--if-no-account"]) == 7
    assert cli.main(["setup-code"]) == 7
    assert calls == [True, False]

import re
from datetime import timedelta

from auth_helpers import EMAIL, PASSWORD, events, load_user, make_user, put_setup_code, sign_in
from sqlalchemy import select

from app.auth import cli
from app.auth.models import AuthSession, RecoveryCode, SetupCode
from app.auth.passwords import verify_password
from app.auth.recovery import CODE_PATTERN, hash_code
from app.core.db import SessionLocal

NEW_PASSWORD = "a brand new and long passphrase"

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


async def session_rows() -> list[AuthSession]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AuthSession))).all())


async def recovery_rows() -> list[RecoveryCode]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(RecoveryCode))).all())


async def test_reset_mfa_forces_enrolment_at_the_next_sign_in(api, clock, capsys):
    await make_user(recovery_codes=["ABCD-EFGH-IJKL-MNOP"])
    assert await cli.reset_mfa("  Owner@Example.com ") == 0
    assert capsys.readouterr().out == (
        f"The second factor of {EMAIL} is reset and 0 sessions ended. "
        "They set up a new authenticator at their next sign-in.\n"
    )
    user = await load_user()
    assert (user.totp_secret, user.totp_pending_secret, user.totp_confirmed_at, user.totp_last_step) == (
        None,
        None,
        None,
        None,
    )
    assert await recovery_rows() == []
    response = await api.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "enrolment_required"}


async def test_reset_mfa_ends_the_sessions_and_records_its_event(api, clock, capsys):
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    assert len(await session_rows()) == 1

    assert await cli.reset_mfa(EMAIL) == 0
    assert "and 1 sessions ended." in capsys.readouterr().out
    assert await session_rows() == []
    assert (await api.get("/api/auth/session")).json()["status"] == "signed_out"
    (event,) = await events("auth.mfa_reset")
    assert (event.actor_type, event.actor_name, event.result) == ("system", "cli", "success")
    assert (event.target_type, event.target_id, event.target_name) == ("user", str(user.id), EMAIL)
    assert event.result_detail == {"sessions_ended": 1}


async def test_reset_mfa_of_an_unknown_email_fails(clean_auth, clock, capsys):
    await make_user()
    assert await cli.reset_mfa("nobody@example.com") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "No account has the email nobody@example.com.\n"
    assert (await load_user()).totp_secret is not None
    assert await events("auth.mfa_reset") == []


async def test_reset_password_sets_the_password_and_clears_the_lock(api, clock, capsys):
    user, secret = await make_user()
    await sign_in(api, clock, secret)
    async with SessionLocal() as db:
        stored = await db.get(type(user), user.id)
        stored.failed_attempts, stored.locked_until = 5, clock.now + timedelta(minutes=15)
        await db.commit()

    assert await cli.reset_password(EMAIL.upper(), NEW_PASSWORD) == 0
    assert capsys.readouterr().out == (
        f"The password of {EMAIL} is changed, the account is unlocked and 1 sessions ended.\n"
    )
    stored = await load_user()
    assert await verify_password(stored.password_hash, NEW_PASSWORD)
    assert (stored.failed_attempts, stored.locked_until, stored.password_changed_at) == (0, None, clock.now)
    assert await session_rows() == []
    (event,) = await events("auth.password_changed")
    assert (event.actor_type, event.actor_name, event.result) == ("system", "cli", "success")
    assert (event.target_type, event.target_id) == ("user", str(user.id))
    assert event.result_detail == {"by": "cli", "sessions_ended": 1}
    response = await api.post("/api/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD})
    assert response.json() == {"status": "mfa_required"}


async def test_reset_password_refuses_a_short_password(clean_auth, clock, capsys):
    user, _ = await make_user()
    assert await cli.reset_password(EMAIL, "too short") == 1
    assert capsys.readouterr() == ("", "A password has 12 to 128 characters.\n")
    assert (await load_user()).password_hash == user.password_hash
    assert await events("auth.password_changed") == []


async def test_reset_password_of_an_unknown_email_fails(clean_auth, clock, capsys):
    assert await cli.reset_password("nobody@example.com", NEW_PASSWORD) == 1
    assert capsys.readouterr() == ("", "No account has the email nobody@example.com.\n")


def test_main_runs_reset_mfa_with_the_email(monkeypatch):
    calls = []

    async def fake(email: str) -> int:
        calls.append(email)
        return 0

    monkeypatch.setattr(cli, "reset_mfa", fake)
    assert cli.main(["reset-mfa", "owner@example.com"]) == 0
    assert calls == ["owner@example.com"]


def test_main_reset_password_asks_twice_and_refuses_a_mismatch(monkeypatch, capsys):
    calls = []

    async def fake(email: str, password: str) -> int:
        calls.append((email, password))
        return 0

    monkeypatch.setattr(cli, "reset_password", fake)
    answers = iter([NEW_PASSWORD, "something else entirely"])
    prompts = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: prompts.append(prompt) or next(answers))
    assert cli.main(["reset-password", EMAIL]) == 1
    assert prompts == ["New password: ", "Repeat it: "]
    assert capsys.readouterr().err == "The passwords do not match.\n"
    assert calls == []

    answers = iter([NEW_PASSWORD, NEW_PASSWORD])
    assert cli.main(["reset-password", EMAIL]) == 0
    assert calls == [(EMAIL, NEW_PASSWORD)]


def test_main_reset_password_refuses_a_short_password_before_it_connects(monkeypatch, capsys):
    async def fake(email: str, password: str) -> int:
        raise AssertionError("reset_password must not run")

    monkeypatch.setattr(cli, "reset_password", fake)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "short")
    assert cli.main(["reset-password", EMAIL]) == 1
    assert capsys.readouterr().err == "A password has 12 to 128 characters.\n"

"""Host commands, run in the backend container: python -m app.auth.cli setup-code [--if-no-account] | reset-mfa EMAIL
| reset-password EMAIL."""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Coroutine
from typing import Any

from sqlalchemy import delete, exists, select

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Actor, Event, record
from app.auth import actions, clock, recovery
from app.auth.models import RecoveryCode, SetupCode, User
from app.auth.passwords import PasswordRuleError, check_rule, hash_password
from app.auth.service import target_of
from app.auth.sessions import end_sessions
from app.core.db import SessionLocal, engine

CLI_ACTOR = Actor.system("cli")


async def create_setup_code(*, if_no_account: bool) -> int:
    """Stores a new setup code in place of any earlier one and prints it. Refuses once an account exists; with
    if_no_account, that refusal is silent and succeeds, so every start of a claimed install can run it."""
    async with SessionLocal() as session:
        if await session.scalar(select(exists().select_from(User))):
            if if_no_account:
                return 0
            print("An account exists already, so setup is closed.", file=sys.stderr)
            return 1
        code = recovery.new_code()
        await session.execute(delete(SetupCode))
        session.add(SetupCode(id=1, code_hash=recovery.hash_code(code)))
        await session.flush()
        await record(session, Event(action=actions.SETUP_CODE_CREATED, actor=CLI_ACTOR))
        await session.commit()
    print(f"Setup code: {code}")
    print("Enter it on the setup page of MegooITAdmin. It works until the Owner account exists.")
    return 0


async def _find_user(session: AsyncSession, email: str) -> User | None:
    """The account of the email, locked for this transaction. Prints the refusal when there is none."""
    user = await session.scalar(select(User).where(User.email == email).with_for_update())
    if user is None:
        print(f"No account has the email {email}.", file=sys.stderr)
    return user


async def reset_mfa(email: str) -> int:
    """Removes the account's authenticator and recovery codes and ends its sessions, so the next sign-in enrols."""
    email = email.strip().lower()
    async with SessionLocal() as session:
        user = await _find_user(session, email)
        if user is None:
            return 1
        user.totp_secret = None
        user.totp_pending_secret = None
        user.totp_confirmed_at = None
        user.totp_last_step = None
        await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        ended = len(await end_sessions(session, user.id))
        await record(
            session,
            Event(
                action=actions.MFA_RESET,
                actor=CLI_ACTOR,
                target=target_of(user),
                result_detail={"sessions_ended": ended},
            ),
        )
        await session.commit()
    print(
        f"The second factor of {email} is reset and {ended} sessions ended. "
        "They set up a new authenticator at their next sign-in."
    )
    return 0


async def reset_password(email: str, password: str) -> int:
    """Sets a new password, clears a lock and ends the account's sessions."""
    email = email.strip().lower()
    async with SessionLocal() as session:
        user = await _find_user(session, email)
        if user is None:
            return 1
        try:
            check_rule(password)
        except PasswordRuleError as error:
            print(error, file=sys.stderr)
            return 1
        user.password_hash = await hash_password(password)
        user.password_changed_at = clock.now()
        user.failed_attempts = 0
        user.locked_until = None
        ended = len(await end_sessions(session, user.id))
        await record(
            session,
            Event(
                action=actions.PASSWORD_CHANGED,
                actor=CLI_ACTOR,
                target=target_of(user),
                result_detail={"by": "cli", "sessions_ended": ended},
            ),
        )
        await session.commit()
    print(f"The password of {email} is changed, the account is unlocked and {ended} sessions ended.")
    return 0


def _ask_password() -> str | None:
    """Asks for the new password twice. Prints the refusal and returns None when it is unusable."""
    password = getpass.getpass("New password: ")
    if getpass.getpass("Repeat it: ") != password:
        print("The passwords do not match.", file=sys.stderr)
        return None
    try:
        check_rule(password)
    except PasswordRuleError as error:
        print(error, file=sys.stderr)
        return None
    return password


async def _run(coro: Coroutine[Any, Any, int]) -> int:
    try:
        return await coro
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    setup_code = commands.add_parser("setup-code", help="Print a new one-time setup code")
    setup_code.add_argument(
        "--if-no-account", action="store_true", help="Print nothing and succeed when an account exists already"
    )
    reset_mfa_command = commands.add_parser("reset-mfa", help="Make EMAIL set up a new authenticator at the next sign-in")
    reset_mfa_command.add_argument("email")
    reset_password_command = commands.add_parser(
        "reset-password", help="Set a new password for EMAIL and unlock the account"
    )
    reset_password_command.add_argument("email")
    args = parser.parse_args(argv)
    if args.command == "reset-mfa":
        return asyncio.run(_run(reset_mfa(args.email)))
    if args.command == "reset-password":
        password = _ask_password()
        if password is None:
            return 1
        return asyncio.run(_run(reset_password(args.email, password)))
    return asyncio.run(_run(create_setup_code(if_no_account=args.if_no_account)))


if __name__ == "__main__":
    sys.exit(main())

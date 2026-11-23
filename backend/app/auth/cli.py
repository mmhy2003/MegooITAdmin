"""Host commands, run in the backend container: python -m app.auth.cli setup-code [--if-no-account]."""

import argparse
import asyncio
import sys
from collections.abc import Coroutine
from typing import Any

from sqlalchemy import delete, exists, select

from app.audit import Actor, Event, record
from app.auth import actions, recovery
from app.auth.models import SetupCode, User
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
    args = parser.parse_args(argv)
    return asyncio.run(_run(create_setup_code(if_no_account=args.if_no_account)))


if __name__ == "__main__":
    sys.exit(main())

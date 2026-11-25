"""The API role megooitadmin_api and the collector role megooitadmin_collector, and the entrypoint step that gives
them their passwords.

Migrations 0003 and 0009 create the roles without login. `python -m app.core.db_roles` runs after
`alembic upgrade head`, as the owner. It gives the API role LOGIN and the password of DATABASE_URL, then the collector
role LOGIN and the password of DATABASE_COLLECTOR_URL; without that variable the collector role is left as it is. Each
password is sent as a SCRAM-SHA-256 verifier, as psql's \\password does, so the plain password never reaches the
database or its log."""

import asyncio
import base64
import hashlib
import hmac
import os
import re
import sys

from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

API_ROLE = "megooitadmin_api"
COLLECTOR_ROLE = "megooitadmin_collector"
SCRAM_ITERATIONS = 4096
UNDEFINED_OBJECT = "42704"
# Only base64, digits, $ and :, so the verifier is safe between the quotes of ALTER ROLE.
_VERIFIER = re.compile(r"SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+")


class ApiRoleError(RuntimeError):
    """A role's password cannot be set. The message names the variable and never holds a URL."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def scram_verifier(password: str, salt: bytes | None = None, iterations: int = SCRAM_ITERATIONS) -> str:
    salt = os.urandom(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    stored_key = hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")
    return f"SCRAM-SHA-256${iterations}:{_b64(salt)}${_b64(stored_key)}:{_b64(server_key)}"


def _password(database_url: str, role: str, variable: str) -> str:
    try:
        url = make_url(database_url)
    except ArgumentError:
        raise ApiRoleError(f"{variable} is not a database URL") from None
    if url.username != role:
        raise ApiRoleError(f"{variable} must connect as {role}")
    password = url.password or ""
    if not password:
        raise ApiRoleError(f"{variable} has no password for {role}")
    if not (password.isascii() and password.isprintable()):
        raise ApiRoleError(f"the password in {variable} must be printable ASCII")
    return password


async def _set_password(owner_url: str, role: str, verifier: str) -> None:
    engine = create_async_engine(owner_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            # exec_driver_sql, not text(): text() would read ":<base64>" inside the verifier as a bind parameter.
            await connection.exec_driver_sql(f"ALTER ROLE {role} WITH LOGIN PASSWORD '{verifier}'")
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == UNDEFINED_OBJECT:
            raise ApiRoleError(
                f"the role {role} does not exist: run the migrations (alembic upgrade head) first"
            ) from None
        raise
    finally:
        await engine.dispose()


def _settings() -> Settings:
    try:
        return get_settings()
    except ValidationError:
        raise ApiRoleError("DATABASE_URL is not set") from None


def _sync(settings: Settings, database_url: str, role: str, variable: str) -> None:
    password = _password(database_url, role, variable)
    if not settings.database_owner_url:
        raise ApiRoleError(f"DATABASE_OWNER_URL is not set: the password of {role} is set as the owner")
    verifier = scram_verifier(password)
    if not _VERIFIER.fullmatch(verifier):
        raise ApiRoleError("the SCRAM verifier has an unexpected shape")
    asyncio.run(_set_password(settings.database_owner_url, role, verifier))


def sync_api_role_password(settings: Settings | None = None) -> None:
    """Gives the API role LOGIN and the password of DATABASE_URL, connected with DATABASE_OWNER_URL. Sync, like
    Alembic's commands: it runs its own event loop."""
    settings = settings or _settings()
    _sync(settings, settings.database_url, API_ROLE, "DATABASE_URL")


def sync_collector_role_password(settings: Settings | None = None) -> bool:
    """Gives the collector role LOGIN and the password of DATABASE_COLLECTOR_URL. False, and nothing changes, when the
    variable is not set."""
    settings = settings or _settings()
    if not settings.database_collector_url:
        return False
    _sync(settings, settings.database_collector_url, COLLECTOR_ROLE, "DATABASE_COLLECTOR_URL")
    return True


def main() -> int:
    role = API_ROLE
    try:
        sync_api_role_password()
        print(f"Set the password of {API_ROLE}.")
        role = COLLECTOR_ROLE
        collector_set = sync_collector_role_password()
    except ApiRoleError as exc:
        print(f"Could not set the password of {role}: {exc}", file=sys.stderr)
        return 1
    if collector_set:
        print(f"Set the password of {COLLECTOR_ROLE}.")
    else:
        print(
            f"DATABASE_COLLECTOR_URL is not set: {COLLECTOR_ROLE} keeps no login, so the collector cannot sign in."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

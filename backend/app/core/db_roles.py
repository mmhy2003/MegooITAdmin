"""The API role megooitadmin_api: the backend serves as it, and the entrypoint gives it its password.

Migration 0003 creates the role without login. `python -m app.core.db_roles` runs after `alembic upgrade head`, as
the owner, and gives the role LOGIN and the password of DATABASE_URL. The password is sent as a SCRAM-SHA-256
verifier, as psql's \\password does, so the plain password never reaches the database or its log."""

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
SCRAM_ITERATIONS = 4096
UNDEFINED_OBJECT = "42704"
# Only base64, digits, $ and :, so the verifier is safe between the quotes of ALTER ROLE.
_VERIFIER = re.compile(r"SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+")


class ApiRoleError(RuntimeError):
    """The API role's password cannot be set. The message names the variable and never holds a URL."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def scram_verifier(password: str, salt: bytes | None = None, iterations: int = SCRAM_ITERATIONS) -> str:
    salt = os.urandom(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    stored_key = hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")
    return f"SCRAM-SHA-256${iterations}:{_b64(salt)}${_b64(stored_key)}:{_b64(server_key)}"


def _api_password(database_url: str) -> str:
    try:
        url = make_url(database_url)
    except ArgumentError:
        raise ApiRoleError("DATABASE_URL is not a database URL") from None
    if url.username != API_ROLE:
        raise ApiRoleError(f"DATABASE_URL must connect as {API_ROLE}: the backend never serves as another role")
    password = url.password or ""
    if not password:
        raise ApiRoleError(f"DATABASE_URL has no password for {API_ROLE}")
    if not (password.isascii() and password.isprintable()):
        raise ApiRoleError("the password in DATABASE_URL must be printable ASCII")
    return password


async def _set_password(owner_url: str, verifier: str) -> None:
    engine = create_async_engine(owner_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            # exec_driver_sql, not text(): text() would read ":<base64>" inside the verifier as a bind parameter.
            await connection.exec_driver_sql(f"ALTER ROLE {API_ROLE} WITH LOGIN PASSWORD '{verifier}'")
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == UNDEFINED_OBJECT:
            raise ApiRoleError(
                f"the role {API_ROLE} does not exist: run the migrations (alembic upgrade head) first"
            ) from None
        raise
    finally:
        await engine.dispose()


def _settings() -> Settings:
    try:
        return get_settings()
    except ValidationError:
        raise ApiRoleError("DATABASE_URL is not set") from None


def sync_api_role_password(settings: Settings | None = None) -> None:
    """Gives the API role LOGIN and the password of DATABASE_URL, connected with DATABASE_OWNER_URL. Sync, like
    Alembic's commands: it runs its own event loop."""
    settings = settings or _settings()
    password = _api_password(settings.database_url)
    if not settings.database_owner_url:
        raise ApiRoleError("DATABASE_OWNER_URL is not set: the API role's password is set as the owner")
    verifier = scram_verifier(password)
    if not _VERIFIER.fullmatch(verifier):
        raise ApiRoleError("the SCRAM verifier has an unexpected shape")
    asyncio.run(_set_password(settings.database_owner_url, verifier))


def main() -> int:
    try:
        sync_api_role_password()
    except ApiRoleError as exc:
        print(f"Could not set the password of {API_ROLE}: {exc}", file=sys.stderr)
        return 1
    print(f"Set the password of {API_ROLE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

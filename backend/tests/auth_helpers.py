"""Shared helpers of the auth tests: accounts, codes, server groups, grants and the audit events they record."""

import json
import uuid
from datetime import datetime

import pyotp
from httpx import AsyncClient
from sqlalchemy import inspect, select, update
from sqlalchemy.dialects.postgresql import insert

from app.access.models import RoleGrant
from app.access.permissions import USUAL, GroupRole, Permission
from app.audit import AuditEvent
from app.auth import clock, totp
from app.auth.crypto import encrypt_secret
from app.auth.models import RecoveryCode, SetupCode, User
from app.auth.passwords import hash_password
from app.auth.recovery import hash_code
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.inventory.models import ServerGroup

EMAIL = "owner@example.com"
NAME = "Olive Owner"
PASSWORD = "correct horse battery staple"


async def make_user(
    *,
    email: str = EMAIL,
    name: str = NAME,
    password: str | None = PASSWORD,
    enrolled: bool = True,
    platform_role: str | None = "owner",
    disabled: bool = False,
    recovery_codes: list[str] = (),
) -> tuple[User, str | None]:
    """Inserts an account through the API role. Returns it and its plain TOTP secret (None when not enrolled).
    `password=None` stores no hash, as for an invited account; `disabled` disables the account now."""
    async with SessionLocal() as session:
        user = User(
            email=email,
            name=name,
            password_hash=None if password is None else await hash_password(password),
            platform_role=platform_role,
            disabled_at=clock.now() if disabled else None,
            password_changed_at=clock.now(),
        )
        session.add(user)
        await session.flush()
        secret = None
        if enrolled:
            secret = totp.new_secret()
            user.totp_secret = encrypt_secret(get_settings().auth_key(), user.id, secret)
            user.totp_confirmed_at = clock.now()
        session.add_all(RecoveryCode(user_id=user.id, code_hash=hash_code(code)) for code in recovery_codes)
        await session.commit()
        return user, secret


def code_for(secret: str, at: datetime) -> str:
    return pyotp.TOTP(secret).at(at)


async def sign_in(api, clock, secret: str, *, email: str = EMAIL, password: str = PASSWORD) -> None:
    """Signs the client in with the password and a TOTP code, then moves the clock on so the next code is new."""
    response = await api.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    response = await api.post("/api/auth/login/mfa", json={"code": code_for(secret, clock.now), "method": "totp"})
    assert response.status_code == 200, response.text
    clock.advance(seconds=30)


async def actions() -> list[str]:
    """The actions of audit_log, oldest first."""
    async with SessionLocal() as session:
        return list((await session.scalars(select(AuditEvent.action).order_by(AuditEvent.seq))).all())


async def events(action: str) -> list[AuditEvent]:
    async with SessionLocal() as session:
        query = select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.seq)
        return list((await session.scalars(query)).all())


async def audit_rows() -> list[str]:
    """Every audit_log row, all its columns, as JSON."""
    async with SessionLocal() as session:
        rows = (await session.scalars(select(AuditEvent).order_by(AuditEvent.seq))).all()
        columns = [c.key for c in inspect(AuditEvent).column_attrs]
        return [json.dumps({key: getattr(row, key) for key in columns}, default=str) for row in rows]


async def load_user(email: str = EMAIL) -> User:
    """A fresh read of the account, past any session's identity map."""
    async with SessionLocal() as session:
        return (await session.scalars(select(User).where(User.email == email))).one()


async def put_setup_code(code: str, failed_attempts: int = 0) -> None:
    """Stores the hash of `code` as the setup code, replacing any earlier one."""
    values = {"code_hash": hash_code(code), "failed_attempts": failed_attempts}
    async with SessionLocal() as session:
        await session.execute(
            insert(SetupCode).values(id=1, **values).on_conflict_do_update(index_elements=["id"], set_=values)
        )
        await session.commit()


def other_client(api) -> AsyncClient:
    """A second browser on the same app."""
    return AsyncClient(transport=api._transport, base_url="http://test")


async def make_group(name: str, description: str | None = None) -> ServerGroup:
    async with SessionLocal() as session:
        group = ServerGroup(name=name, description=description)
        session.add(group)
        await session.commit()
        return group


async def add_grant(user_id: uuid.UUID, group_id: uuid.UUID, role: str = "admin", **switches: bool) -> RoleGrant:
    """Gives the person `role` in the group with the role's usual switches, each one overridable by name."""
    values = {p.value: p in USUAL[GroupRole(role)] for p in Permission} | switches
    async with SessionLocal() as session:
        grant = RoleGrant(user_id=user_id, server_group_id=group_id, role=role, **values)
        session.add(grant)
        await session.commit()
        return grant


async def set_switch(grant_id: uuid.UUID, name: str, value: bool) -> None:
    async with SessionLocal() as session:
        await session.execute(update(RoleGrant).where(RoleGrant.id == grant_id).values({name: value}))
        await session.commit()

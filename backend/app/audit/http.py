"""The HTTP side of the audit log: routes declare the events they record, and the source of a request."""

import ipaddress
import re
from collections.abc import AsyncIterator

from fastapi import Depends, params
from starlette.requests import HTTPConnection

from app.audit.events import ACTION_PATTERN, Source
from app.audit.writer import AUDIT_ACTIONS
from app.core.db import DbSession


class AuditMissing(RuntimeError):
    """A state-changing route ended without recording any of its declared actions."""


def audited(*actions: str) -> params.Depends:
    """A route dependency: the request is rolled back and answered with 500 unless it records one of `actions`."""
    if not actions:
        raise ValueError("audited() needs at least one action")
    for action in actions:
        if not re.fullmatch(ACTION_PATTERN, action):
            raise ValueError(f"{action!r} is not a dotted action name such as 'server.created'")
    declared = frozenset(actions)

    async def audit_guard(session: DbSession) -> AsyncIterator[None]:
        yield
        # Reached only when the handler returned. When it raised, the exception passes through here
        # and get_session rolls back.
        if not declared & session.info.get(AUDIT_ACTIONS, set()):
            raise AuditMissing(f"{', '.join(sorted(declared))}: no event was recorded, so nothing is committed")

    audit_guard.audit_actions = declared  # read by tests/security/routes.py
    return Depends(audit_guard, scope="function")


def source_of(connection: HTTPConnection, *, auth_method: str | None = None, mfa: bool | None = None) -> Source:
    """Where a request or a socket came from. Uvicorn's --proxy-headers already set connection.client from
    X-Forwarded-For. A host that is not an IP address (Starlette's TestClient sends "testclient") gives ip=None."""
    ip = None
    if connection.client is not None:
        try:
            ip = str(ipaddress.ip_address(connection.client.host))
        except ValueError:
            ip = None
    return Source(ip=ip, user_agent=connection.headers.get("user-agent"), auth_method=auth_method, mfa=mfa)

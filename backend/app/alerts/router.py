"""The routes under /api/alert-rules: the Owner lists, creates, changes and deletes the alert rules. Under
/api/alerts each signed-in person reads the alerts of the servers they see, and the bell's events, and moves their own
read mark; GET /api/servers/{id}/alerts gives whoever sees a server its alerts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.access.deps import CurrentAccess, require_group_visible, require_owner
from app.alerts import actions, service
from app.alerts.schemas import AlertEventsOut, AlertOut, AlertRuleIn, AlertRuleOut, AlertRulePatch
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession
from app.inventory.deps import group_of_server

rules_router = APIRouter(prefix="/alert-rules")
alerts_router = APIRouter(prefix="/alerts")
server_alerts_router = APIRouter()


@rules_router.get("", dependencies=[Depends(require_owner)])
async def list_rules(db: DbSession) -> list[AlertRuleOut]:
    return await service.list_rules(db)


@rules_router.post("", dependencies=[Depends(require_owner), audited(actions.ALERT_RULE_CREATED)])
async def create_rule(body: AlertRuleIn, request: Request, db: DbSession, user: CurrentUser) -> AlertRuleOut:
    # `user` is the Owner who creates the rule.
    return await service.create_rule(db, request, user, body)


@rules_router.patch("/{rule_id}", dependencies=[Depends(require_owner), audited(actions.ALERT_RULE_CHANGED)])
async def update_rule(
    rule_id: UUID, body: AlertRulePatch, request: Request, db: DbSession, user: CurrentUser
) -> AlertRuleOut:
    return await service.update_rule(db, request, user, rule_id, body)


@rules_router.delete(
    "/{rule_id}", status_code=204, dependencies=[Depends(require_owner), audited(actions.ALERT_RULE_DELETED)]
)
async def delete_rule(rule_id: UUID, request: Request, db: DbSession, user: CurrentUser) -> Response:
    await service.delete_rule(db, request, user, rule_id)
    return Response(status_code=204)


@alerts_router.get("")
async def list_alerts(
    db: DbSession,
    access: CurrentAccess,
    state: Literal["firing", "closed"] = "firing",
    group_id: UUID | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=service.PAGE)] = service.PAGE,
) -> list[AlertOut]:
    return await service.list_alerts(db, access, state, group_id, tag or [], before, limit)


@alerts_router.get("/events")
async def read_events(db: DbSession, access: CurrentAccess, user: CurrentUser) -> AlertEventsOut:
    return await service.read_events(db, access, user)


@alerts_router.post("/seen", status_code=204)
async def mark_seen(user: CurrentUser) -> Response:
    service.mark_seen(user)
    return Response(status_code=204)


@server_alerts_router.get(
    "/servers/{server_id}/alerts", dependencies=[Depends(require_group_visible(group=group_of_server))]
)
async def server_alerts(server_id: UUID, db: DbSession, before: datetime | None = None) -> list[AlertOut]:
    return await service.server_alerts(db, server_id, before)

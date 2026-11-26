"""The routes under /api/alert-rules: the Owner lists, creates, changes and deletes the alert rules."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.access.deps import require_owner
from app.alerts import actions, service
from app.alerts.schemas import AlertRuleIn, AlertRuleOut, AlertRulePatch
from app.audit import audited
from app.auth.deps import CurrentUser
from app.core.db import DbSession

rules_router = APIRouter(prefix="/alert-rules")


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

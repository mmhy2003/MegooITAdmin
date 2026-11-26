"""The alert rules the Owner creates, changes and deletes, between the routes and the tables."""

from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import actions
from app.alerts.catalog import CATALOG
from app.alerts.models import Alert, AlertRule
from app.alerts.schemas import AlertRuleIn, AlertRuleOut, AlertRulePatch
from app.audit import Target, changes, record
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.core.db import flush_unique
from app.inventory.models import Server, ServerGroup

FIELDS = (
    "name",
    "metric",
    "comparison",
    "threshold",
    "duration_seconds",
    "severity",
    "server_group_id",
    "server_id",
    "enabled",
)
# A change of one of these raises the revision, so the collector starts counting again. A rename or a switch does not.
CONDITION = ("metric", "comparison", "threshold", "duration_seconds", "severity", "server_group_id", "server_id")
# A field the Owner cannot clear: a PATCH that sends it as None keeps it.
REQUIRED = frozenset({"name", "metric", "duration_seconds", "severity", "enabled"})


def _values(rule: AlertRule) -> dict[str, Any]:
    return {field: getattr(rule, field) for field in FIELDS}


def _audited(values: dict[str, Any]) -> dict[str, Any]:
    """The values as an event holds them: the threshold as text (the audit log refuses floats), IDs as text."""
    threshold, group_id, server_id = values["threshold"], values["server_group_id"], values["server_id"]
    return values | {
        "threshold": None if threshold is None else format(threshold, "g"),
        "server_group_id": None if group_id is None else str(group_id),
        "server_id": None if server_id is None else str(server_id),
    }


def _fields(rule: AlertRule) -> dict[str, Any]:
    """The fields of a rule its events compare."""
    return _audited(_values(rule))


def _target(rule: AlertRule) -> Target:
    return Target(type="alert_rule", id=str(rule.id), name=rule.name)


async def _check(db: AsyncSession, values: dict[str, Any]) -> None:
    """The rule the values make: its condition fits its metric, and its scope is at most one group or server that
    exists. 422 otherwise."""
    spec = CATALOG[values["metric"]]
    comparison, threshold = values["comparison"], values["threshold"]
    if spec.maximum is None:
        if comparison is not None or threshold is not None:
            raise HTTPException(422, "bad_threshold")
    elif comparison is None or threshold is None or not 0 <= threshold <= spec.maximum:
        raise HTTPException(422, "bad_threshold")
    group_id, server_id = values["server_group_id"], values["server_id"]
    if group_id is not None and server_id is not None:
        raise HTTPException(422, "bad_scope")
    if group_id is not None and await db.scalar(select(ServerGroup.id).where(ServerGroup.id == group_id)) is None:
        raise HTTPException(422, "unknown_group")
    if server_id is not None and await db.scalar(select(Server.id).where(Server.id == server_id)) is None:
        raise HTTPException(422, "unknown_server")


async def _check_name(db: AsyncSession, name: str, rule_id: UUID | None = None) -> None:
    """Another rule with the name, without regard to case: 409."""
    query = select(AlertRule.id).where(func.lower(AlertRule.name) == name.lower())
    if rule_id is not None:
        query = query.where(AlertRule.id != rule_id)
    if await db.scalar(query) is not None:
        raise HTTPException(409, "rule_name_taken")


async def _firing_counts(db: AsyncSession) -> dict[UUID, int]:
    """How many alerts of each rule are firing."""
    query = select(Alert.rule_id, func.count()).where(Alert.state == "firing").group_by(Alert.rule_id)
    return dict((await db.execute(query)).all())


def _query():
    return (
        select(AlertRule, ServerGroup.name, Server.name)
        .outerjoin(ServerGroup, ServerGroup.id == AlertRule.server_group_id)
        .outerjoin(Server, Server.id == AlertRule.server_id)
    )


def _out(rule: AlertRule, group_name: str | None, server_name: str | None, firing_count: int) -> AlertRuleOut:
    return AlertRuleOut(
        **_values(rule),
        id=rule.id,
        server_group_name=group_name,
        server_name=server_name,
        revision=rule.revision,
        suggested_playbook_id=rule.suggested_playbook_id,
        firing_count=firing_count,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


async def _out_of(db: AsyncSession, rule: AlertRule) -> AlertRuleOut:
    _, group_name, server_name = (await db.execute(_query().where(AlertRule.id == rule.id))).one()
    return _out(rule, group_name, server_name, (await _firing_counts(db)).get(rule.id, 0))


async def list_rules(db: AsyncSession) -> list[AlertRuleOut]:
    """Every rule, by name, with how many of its alerts are firing."""
    rows = (await db.execute(_query().order_by(func.lower(AlertRule.name), AlertRule.id))).all()
    firing = await _firing_counts(db)
    return [_out(rule, group_name, server_name, firing.get(rule.id, 0)) for rule, group_name, server_name in rows]


async def create_rule(db: AsyncSession, request: Request, owner: User, body: AlertRuleIn) -> AlertRuleOut:
    values = body.model_dump(include=set(FIELDS))
    await _check(db, values)
    await _check_name(db, body.name)
    rule = AlertRule(**values)
    db.add(rule)
    await flush_unique(db, "alert_rules_name_key", "rule_name_taken")
    await db.refresh(rule)
    out = await _out_of(db, rule)
    # record() last: it holds the audit chain lock until the commit.
    await record(
        db,
        auth_event(
            request,
            actions.ALERT_RULE_CREATED,
            actor_of(owner),
            mfa=True,
            target=_target(rule),
            change=changes({}, _fields(rule)),
        ),
    )
    return out


async def update_rule(
    db: AsyncSession, request: Request, owner: User, rule_id: UUID, body: AlertRulePatch
) -> AlertRuleOut:
    """Changes the fields sent, and checks the rule they make. Nothing differs: 409."""
    rule = await db.scalar(select(AlertRule).where(AlertRule.id == rule_id).with_for_update())
    if rule is None:
        raise HTTPException(404, "not_found")
    before = _values(rule)
    sent = {field: getattr(body, field) for field in body.model_fields_set}
    after = before | {field: value for field, value in sent.items() if value is not None or field not in REQUIRED}
    change = changes(_audited(before), _audited(after))
    if change is None:
        raise HTTPException(409, "no_change")
    await _check(db, after)
    if after["name"] != before["name"]:
        await _check_name(db, after["name"], rule.id)
    for field, value in after.items():
        setattr(rule, field, value)
    if any(after[field] != before[field] for field in CONDITION):
        rule.revision += 1
    rule.updated_at = func.now()
    await flush_unique(db, "alert_rules_name_key", "rule_name_taken")
    await db.refresh(rule)
    out = await _out_of(db, rule)
    await record(
        db,
        auth_event(
            request,
            actions.ALERT_RULE_CHANGED,
            actor_of(owner),
            mfa=True,
            # The rule as it is named now; the change holds the old name.
            target=_target(rule),
            change=change,
        ),
    )
    return out


async def delete_rule(db: AsyncSession, request: Request, owner: User, rule_id: UUID) -> None:
    """Deletes the rule. Its alerts keep their copy of it; the collector ends those still firing."""
    rule = await db.scalar(select(AlertRule).where(AlertRule.id == rule_id).with_for_update())
    if rule is None:
        raise HTTPException(404, "not_found")
    deleted = auth_event(
        request,
        actions.ALERT_RULE_DELETED,
        actor_of(owner),
        mfa=True,
        target=_target(rule),
        change=changes(_fields(rule), {}),
    )
    await db.delete(rule)
    await db.flush()
    await record(db, deleted)

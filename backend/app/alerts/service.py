"""The alert rules the Owner creates, changes and deletes, and the alerts and events people read, between the routes
and the tables."""

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import actions
from app.alerts.catalog import CATALOG
from app.access.permissions import Access
from app.alerts.models import Alert, AlertEvent, AlertRule
from app.alerts.schemas import AlertEventOut, AlertEventsOut, AlertOut, AlertRuleIn, AlertRuleOut, AlertRulePatch
from app.audit import Event, Target, changes, record
from app.auth import clock
from app.auth.models import User
from app.auth.service import actor_of, auth_event
from app.core.db import flush_unique
from app.inventory.models import Server, ServerGroup, ServerTag

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
    """On how many servers each rule fires: a server firing on two filesystems counts once."""
    query = (
        select(Alert.rule_id, func.count(func.distinct(Alert.server_id)))
        .where(Alert.state == "firing")
        .group_by(Alert.rule_id)
    )
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


def _deleted(request: Request, user: User, rule: AlertRule) -> Event:
    return auth_event(
        request,
        actions.ALERT_RULE_DELETED,
        actor_of(user),
        mfa=True,
        target=_target(rule),
        change=changes(_fields(rule), {}),
    )


async def delete_rule(db: AsyncSession, request: Request, owner: User, rule_id: UUID) -> None:
    """Deletes the rule. Its alerts keep their copy of it; the collector ends those still firing."""
    rule = await db.scalar(select(AlertRule).where(AlertRule.id == rule_id).with_for_update())
    if rule is None:
        raise HTTPException(404, "not_found")
    deleted = _deleted(request, owner, rule)
    await db.delete(rule)
    await db.flush()
    await record(db, deleted)


async def delete_rules_of(
    db: AsyncSession, request: Request, user: User, *, group_id: UUID | None = None, server_id: UUID | None = None
) -> list[Event]:
    """Deletes the rules scoped to the group or the server that is being deleted, by name, and gives their
    deletion events for the caller to record before its own."""
    scope = AlertRule.server_group_id == group_id if group_id is not None else AlertRule.server_id == server_id
    query = select(AlertRule).where(scope).order_by(func.lower(AlertRule.name), AlertRule.id).with_for_update()
    rules = list((await db.scalars(query)).all())
    events = [_deleted(request, user, rule) for rule in rules]
    for rule in rules:
        await db.delete(rule)
    return events


# How far back the closed alerts and the bell's events go, how many closed alerts a page holds, and how many events
# the bell shows.
HISTORY = timedelta(days=30)
PAGE = 50
LATEST_EVENTS = 10
ALERT_FIELDS = (
    "id",
    "server_id",
    "rule_id",
    "rule_name",
    "metric",
    "comparison",
    "threshold",
    "duration_seconds",
    "severity",
    "instance",
    "state",
    "end_reason",
    "fired_at",
    "resolved_at",
    "value",
    "last_value",
    "peak_value",
)


def _visible(query, access: Access):
    """The query, kept to the servers the person sees."""
    visible = access.visible_group_ids()
    return query if visible is None else query.where(Server.server_group_id.in_(visible))


def _alerts_query():
    return (
        select(Alert, Server.name, ServerGroup.id, ServerGroup.name)
        .join(Server, Server.id == Alert.server_id)
        .join(ServerGroup, ServerGroup.id == Server.server_group_id)
    )


def _alert_out(alert: Alert, server_name: str, group_id: UUID, group_name: str) -> AlertOut:
    return AlertOut(
        **{field: getattr(alert, field) for field in ALERT_FIELDS},
        server_name=server_name,
        group_id=group_id,
        group_name=group_name,
    )


def _firing(query):
    return query.where(Alert.state == "firing").order_by(Alert.fired_at.desc(), Alert.id.desc())


def _closed(query, before: datetime | None, before_id: UUID | None, limit: int):
    """The resolved and ended alerts, newest first, after the cursor when given: older than `before`, or, with
    `before_id`, resolved at `before` and listed after that alert. The collector ends many alerts with one time."""
    query = query.where(Alert.state != "firing")
    if before is not None and before_id is not None:
        query = query.where(tuple_(Alert.resolved_at, Alert.id) < tuple_(before, before_id))
    elif before is not None:
        query = query.where(Alert.resolved_at < before)
    return query.order_by(Alert.resolved_at.desc(), Alert.id.desc()).limit(limit)


async def _alerts(db: AsyncSession, query) -> list[AlertOut]:
    return [_alert_out(*row) for row in (await db.execute(query)).all()]


async def list_alerts(
    db: AsyncSession,
    access: Access,
    state: Literal["firing", "closed"],
    group_id: UUID | None,
    tags: list[str],
    before: datetime | None,
    before_id: UUID | None,
    limit: int,
) -> list[AlertOut]:
    """The alerts of the servers the person sees, in one group when asked, carrying every tag asked for: every
    firing one, newest first, or a page of those closed in the last 30 days, newest first."""
    query = _visible(_alerts_query(), access)
    if group_id is not None:
        query = query.where(Server.server_group_id == group_id)
    for tag in {tag.strip().lower() for tag in tags}:
        query = query.where(Server.id.in_(select(ServerTag.server_id).where(ServerTag.tag == tag)))
    if state == "firing":
        return await _alerts(db, _firing(query))
    return await _alerts(db, _closed(query.where(Alert.resolved_at >= clock.now() - HISTORY), before, before_id, limit))


async def server_alerts(
    db: AsyncSession, server_id: UUID, before: datetime | None, before_id: UUID | None, limit: int
) -> list[AlertOut]:
    """The server's alerts: without `before`, every firing one then the first page of its whole history; with it,
    the page of its history after that cursor (see `_closed`)."""
    query = _alerts_query().where(Alert.server_id == server_id)
    closed = await _alerts(db, _closed(query, before, before_id, limit))
    return closed if before is not None else await _alerts(db, _firing(query)) + closed


async def read_events(db: AsyncSession, access: Access, user: User) -> AlertEventsOut:
    """The bell: how many events of the last 30 days on the servers the person sees came after they last opened it,
    how many of those servers' alerts are firing, and the latest events."""
    since = clock.now() - HISTORY
    seen = since if user.alerts_seen_at is None else max(since, user.alerts_seen_at)
    unseen_query = _visible(
        select(func.count())
        .select_from(AlertEvent)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .join(Server, Server.id == Alert.server_id)
        .where(AlertEvent.at > seen),
        access,
    )
    firing_query = _visible(
        select(func.count()).select_from(Alert).join(Server, Server.id == Alert.server_id), access
    ).where(Alert.state == "firing")
    events_query = (
        _visible(
            select(AlertEvent, Alert, Server.name, ServerGroup.id, ServerGroup.name)
            .join(Alert, Alert.id == AlertEvent.alert_id)
            .join(Server, Server.id == Alert.server_id)
            .join(ServerGroup, ServerGroup.id == Server.server_group_id),
            access,
        )
        .where(AlertEvent.at >= since)
        .order_by(AlertEvent.at.desc(), AlertEvent.id.desc())
        .limit(LATEST_EVENTS)
    )
    events = [
        AlertEventOut(id=event.id, kind=event.kind, at=event.at, alert=_alert_out(*alert))
        for event, *alert in (await db.execute(events_query)).all()
    ]
    return AlertEventsOut(unseen=await db.scalar(unseen_query), firing=await db.scalar(firing_query), events=events)


def mark_seen(user: User) -> None:
    """The person has seen every event until now."""
    user.alerts_seen_at = clock.now()

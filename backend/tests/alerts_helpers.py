"""Shared helpers of the alert tests: rules, the alerts and events the collector wrote, notification channels and
the email settings, all as the owner."""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from app.alerts.models import Alert, AlertEvent, AlertRule
from app.notify.crypto import EMAIL_ROW, seal
from app.notify.models import NotificationChannel, NotificationEmail
from conftest import owner_session

RULE_DEFAULTS: dict[str, Any] = {
    "name": "Test rule",
    "metric": "disk.used_percent",
    "comparison": "above",
    "threshold": 50,
    "duration_seconds": 0,
    "severity": "critical",
}


async def make_rule(**fields: Any) -> AlertRule:
    async with owner_session() as session:
        rule = AlertRule(**(RULE_DEFAULTS | fields))
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule


STARTER_RULES: tuple[dict[str, Any], ...] = (
    {"name": "Filesystem almost full", "metric": "disk.used_percent", "threshold": 90, "duration_seconds": 600},
    {"name": "Memory almost full", "metric": "mem.used_percent", "threshold": 90, "duration_seconds": 600},
    {"name": "CPU busy", "metric": "cpu.used_percent", "threshold": 90, "duration_seconds": 900},
    {"name": "Server unreachable", "metric": "unreachable", "comparison": None, "threshold": None},
)
STARTER_SEVERITIES = ("critical", "warning", "warning", "critical")


async def starter_rules() -> list[AlertRule]:
    """The four rules migration 0011 inserts, which clean_alerts removes."""
    return [
        await make_rule(**({"comparison": "above", "duration_seconds": 300, "severity": severity} | fields))
        for fields, severity in zip(STARTER_RULES, STARTER_SEVERITIES, strict=True)
    ]


async def make_alert(
    server_id: uuid.UUID,
    *,
    state: str = "firing",
    fired_at: datetime,
    resolved_at: datetime | None = None,
    rule: AlertRule | None = None,
    instance: str = "/",
    kind_events: Sequence[str] = ("fired",),
) -> Alert:
    """An alert as the collector writes it, with the rule's copy (the defaults without a rule, as after a deletion),
    and its events: "fired" at fired_at, the others at resolved_at."""
    copy = RULE_DEFAULTS if rule is None else {field: getattr(rule, field) for field in RULE_DEFAULTS}
    async with owner_session() as session:
        alert = Alert(
            server_id=server_id,
            rule_id=None if rule is None else rule.id,
            rule_name=copy["name"],
            metric=copy["metric"],
            comparison=copy["comparison"],
            threshold=copy["threshold"],
            duration_seconds=copy["duration_seconds"],
            severity=copy["severity"],
            instance=instance,
            state=state,
            end_reason="rule_changed" if state == "ended" else None,
            fired_at=fired_at,
            resolved_at=resolved_at,
            value=93.4,
            last_value=93.4 if state == "firing" else 41.0,
            peak_value=95.0,
        )
        session.add(alert)
        await session.flush()
        session.add_all(
            AlertEvent(alert_id=alert.id, kind=kind, at=fired_at if kind == "fired" else resolved_at)
            for kind in kind_events
        )
        await session.commit()
        await session.refresh(alert)
        return alert


async def alerts_of(server_id: uuid.UUID) -> list[Alert]:
    """The server's alerts, oldest first."""
    async with owner_session() as session:
        query = select(Alert).where(Alert.server_id == server_id).order_by(Alert.fired_at, Alert.id)
        return list((await session.scalars(query)).all())


async def events_of(alert_id: uuid.UUID) -> list[AlertEvent]:
    """The alert's events, oldest first."""
    async with owner_session() as session:
        query = select(AlertEvent).where(AlertEvent.alert_id == alert_id).order_by(AlertEvent.at)
        return list((await session.scalars(query)).all())


async def make_channel(kind: str, secret: dict[str, str], **fields: Any) -> NotificationChannel:
    """A channel with its secret ({"url": ...}, or {"bot_token": ..., "chat_id": ...}) sealed to its row."""
    channel_id = uuid.uuid4()
    values = {"name": f"{kind} {channel_id.hex[:6]}", "hint": "test", **fields}
    async with owner_session() as session:
        secret_blob = seal(json.dumps(secret), channel_id.bytes)
        channel = NotificationChannel(id=channel_id, kind=kind, secret=secret_blob, **values)
        session.add(channel)
        await session.commit()
        return channel


async def set_email(**fields: Any) -> None:
    """Changes the email settings. A plain `password` is sealed to the email row."""
    if fields.get("password") is not None:
        fields["password"] = seal(fields["password"], EMAIL_ROW)
    async with owner_session() as session:
        await session.execute(update(NotificationEmail).where(NotificationEmail.id == 1).values(**fields))
        await session.commit()

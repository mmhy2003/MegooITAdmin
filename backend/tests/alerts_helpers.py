"""Shared helpers of the alert tests: rules, and the alerts and events the collector wrote, all as the owner."""

import uuid
from typing import Any

from sqlalchemy import select

from app.alerts.models import Alert, AlertEvent, AlertRule
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

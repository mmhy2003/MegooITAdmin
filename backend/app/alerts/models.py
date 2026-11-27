"""The alert rules, the alerts they fired with their copy of the rule, and the events of each alert."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

METRIC_CHECK = (
    "metric IN ('cpu.used_percent', 'mem.used_percent', 'disk.used_percent', 'disk.inodes_used_percent',"
    " 'load.1m', 'load.5m', 'load.15m', 'unreachable')"
)
# unreachable has no comparison and no threshold. A load is per core, up to 1000; the others are percentages.
CONDITION_CHECK = (
    "(metric = 'unreachable' AND comparison IS NULL AND threshold IS NULL)"
    " OR (metric <> 'unreachable' AND comparison IS NOT NULL AND comparison IN ('above', 'below')"
    " AND threshold IS NOT NULL AND threshold >= 0"
    " AND threshold <= CASE WHEN metric LIKE 'load.%' THEN 1000 ELSE 100 END)"
)
SEVERITY_CHECK = "severity IN ('warning', 'critical')"
END_REASON_CHECK = (
    "(state = 'ended') = (end_reason IS NOT NULL) AND (end_reason IS NULL"
    " OR end_reason IN ('rule_changed', 'rule_disabled', 'rule_deleted', 'server_not_monitored'))"
)


class AlertRule(Base):
    """A threshold held for a duration, on all servers, one server group or one server."""

    __tablename__ = "alert_rules"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="alert_rules_pkey"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="alert_rules_name_check"),
        CheckConstraint(METRIC_CHECK, name="alert_rules_metric_check"),
        CheckConstraint(CONDITION_CHECK, name="alert_rules_condition_check"),
        CheckConstraint("duration_seconds BETWEEN 0 AND 86400", name="alert_rules_duration_check"),
        CheckConstraint(SEVERITY_CHECK, name="alert_rules_severity_check"),
        CheckConstraint("num_nonnulls(server_group_id, server_id) <= 1", name="alert_rules_scope_check"),
        ForeignKeyConstraint(
            ["server_group_id"], ["server_groups.id"], ondelete="CASCADE", name="alert_rules_server_group_id_fkey"
        ),
        ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="alert_rules_server_id_fkey"),
        # Names are unique without regard to case.
        Index("alert_rules_name_key", text("lower(name)"), unique=True),
        Index("alert_rules_server_group_id_idx", "server_group_id"),
        Index("alert_rules_server_id_idx", "server_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(Text)
    comparison: Mapped[str | None] = mapped_column(Text)
    threshold: Mapped[float | None] = mapped_column(Double)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(Text)
    # Both None: every server.
    server_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    server_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Goes up when the condition changes: the collector starts counting again.
    revision: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # The playbook the alert card offers to run (Phase 7). No foreign key until playbooks exist.
    suggested_playbook_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    """One firing of a rule on a server and instance (a mount point, or "" for the whole server), with the rule as it
    was then. At most one is firing per rule, server and instance."""

    __tablename__ = "alerts"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="alerts_pkey"),
        ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="alerts_server_id_fkey"),
        ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="SET NULL", name="alerts_rule_id_fkey"),
        CheckConstraint(SEVERITY_CHECK, name="alerts_severity_check"),
        CheckConstraint("state IN ('firing', 'resolved', 'ended')", name="alerts_state_check"),
        CheckConstraint(END_REASON_CHECK, name="alerts_end_reason_check"),
        CheckConstraint("(state = 'firing') = (resolved_at IS NULL)", name="alerts_resolved_check"),
        Index(
            "alerts_one_firing_key",
            "rule_id",
            "server_id",
            "instance",
            unique=True,
            postgresql_where=text("state = 'firing'"),
        ),
        Index("alerts_server_id_fired_at_idx", "server_id", "fired_at"),
        Index("alerts_resolved_at_idx", "resolved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # None once the rule is deleted.
    rule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rule_name: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(Text)
    comparison: Mapped[str | None] = mapped_column(Text)
    threshold: Mapped[float | None] = mapped_column(Double)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(Text)
    instance: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    end_reason: Mapped[str | None] = mapped_column(Text)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # When it resolved or ended.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # None for unreachable alerts. peak_value is the maximum for "above", the minimum for "below".
    value: Mapped[float | None] = mapped_column(Double)
    last_value: Mapped[float | None] = mapped_column(Double)
    peak_value: Mapped[float | None] = mapped_column(Double)


class AlertEvent(Base):
    """An alert fired, resolved or ended. The sender sends one message per event."""

    __tablename__ = "alert_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="alert_events_pkey"),
        ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE", name="alert_events_alert_id_fkey"),
        CheckConstraint("kind IN ('fired', 'resolved', 'ended')", name="alert_events_kind_check"),
        Index("alert_events_at_idx", "at"),
        Index("alert_events_undispatched_idx", "at", postgresql_where=text("dispatched_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set by the sender once it has queued the event's deliveries.
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

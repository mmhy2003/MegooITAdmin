"""alerts: the alert rules, the alerts with their events, and the notification channels with their deliveries

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API = "megooitadmin_api"
COLLECTOR = "megooitadmin_collector"
METRIC_CHECK = (
    "metric IN ('cpu.used_percent', 'mem.used_percent', 'disk.used_percent', 'disk.inodes_used_percent',"
    " 'load.1m', 'load.5m', 'load.15m', 'unreachable')"
)
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
STARTER_RULES = (
    ("Filesystem almost full", "disk.used_percent", "'above'", "90", 600, "critical"),
    ("Memory almost full", "mem.used_percent", "'above'", "90", 600, "warning"),
    ("CPU busy", "cpu.used_percent", "'above'", "90", 900, "warning"),
    ("Server unreachable", "unreachable", "NULL", "NULL", 300, "critical"),
)


def _times(*names: str) -> list[sa.Column]:
    return [
        sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False) for name in names
    ]


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("comparison", sa.Text(), nullable=True),
        sa.Column("threshold", sa.Double(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("server_group_id", sa.Uuid(), nullable=True),
        sa.Column("server_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        # The playbook the alert card offers to run (Phase 7). No foreign key until playbooks exist.
        sa.Column("suggested_playbook_id", sa.Uuid(), nullable=True),
        *_times("created_at", "updated_at"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="alert_rules_name_check"),
        sa.CheckConstraint(METRIC_CHECK, name="alert_rules_metric_check"),
        sa.CheckConstraint(CONDITION_CHECK, name="alert_rules_condition_check"),
        sa.CheckConstraint("duration_seconds BETWEEN 0 AND 86400", name="alert_rules_duration_check"),
        sa.CheckConstraint(SEVERITY_CHECK, name="alert_rules_severity_check"),
        # All servers, one group or one server.
        sa.CheckConstraint("num_nonnulls(server_group_id, server_id) <= 1", name="alert_rules_scope_check"),
        sa.ForeignKeyConstraint(
            ["server_group_id"], ["server_groups.id"], ondelete="CASCADE", name="alert_rules_server_group_id_fkey"
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="alert_rules_server_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="alert_rules_pkey"),
    )
    op.create_index("alert_rules_name_key", "alert_rules", [sa.text("lower(name)")], unique=True)
    op.create_index("alert_rules_server_group_id_idx", "alert_rules", ["server_group_id"])
    op.create_index("alert_rules_server_id_idx", "alert_rules", ["server_id"])
    for name, metric, comparison, threshold, duration, severity in STARTER_RULES:
        op.execute(
            "INSERT INTO alert_rules (id, name, metric, comparison, threshold, duration_seconds, severity)"
            f" VALUES (gen_random_uuid(), '{name}', '{metric}', {comparison}, {threshold}, {duration}, '{severity}')"
        )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        # A copy of the rule as it was when the alert fired.
        sa.Column("rule_name", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("comparison", sa.Text(), nullable=True),
        sa.Column("threshold", sa.Double(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("value", sa.Double(), nullable=True),
        sa.Column("last_value", sa.Double(), nullable=True),
        sa.Column("peak_value", sa.Double(), nullable=True),
        sa.CheckConstraint(SEVERITY_CHECK, name="alerts_severity_check"),
        sa.CheckConstraint("state IN ('firing', 'resolved', 'ended')", name="alerts_state_check"),
        sa.CheckConstraint(END_REASON_CHECK, name="alerts_end_reason_check"),
        sa.CheckConstraint("(state = 'firing') = (resolved_at IS NULL)", name="alerts_resolved_check"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="alerts_server_id_fkey"),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="SET NULL", name="alerts_rule_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="alerts_pkey"),
    )
    op.create_index(
        "alerts_one_firing_key",
        "alerts",
        ["rule_id", "server_id", "instance"],
        unique=True,
        postgresql_where=sa.text("state = 'firing'"),
    )
    op.create_index("alerts_server_id_fired_at_idx", "alerts", ["server_id", "fired_at"])
    op.create_index("alerts_resolved_at_idx", "alerts", ["resolved_at"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        # Set by the sender once it has queued the event's deliveries.
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('fired', 'resolved', 'ended')", name="alert_events_kind_check"),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE", name="alert_events_alert_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="alert_events_pkey"),
    )
    op.create_index("alert_events_at_idx", "alert_events", ["at"])
    op.create_index(
        "alert_events_undispatched_idx", "alert_events", ["at"], postgresql_where=sa.text("dispatched_at IS NULL")
    )

    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("min_severity", sa.Text(), server_default=sa.text("'warning'"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        # The URL or the bot token and chat, sealed with the notification key. hint is what the pages show of it.
        sa.Column("secret", sa.LargeBinary(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=False),
        *_times("created_at", "updated_at"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="notification_channels_name_check"),
        sa.CheckConstraint(
            "kind IN ('webhook_json', 'webhook_slack', 'telegram')", name="notification_channels_kind_check"
        ),
        sa.CheckConstraint(
            "min_severity IN ('warning', 'critical')", name="notification_channels_min_severity_check"
        ),
        sa.PrimaryKeyConstraint("id", name="notification_channels_pkey"),
    )
    op.create_index("notification_channels_name_key", "notification_channels", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "notification_email",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("host", sa.Text(), nullable=True),
        sa.Column("port", sa.Integer(), server_default=sa.text("587"), nullable=False),
        sa.Column("security", sa.Text(), server_default=sa.text("'starttls'"), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("password", sa.LargeBinary(), nullable=True),
        sa.Column("from_name", sa.Text(), server_default=sa.text("'MegooITAdmin'"), nullable=False),
        sa.Column("from_address", sa.Text(), nullable=True),
        sa.Column(
            "extra_addresses", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("min_severity", sa.Text(), server_default=sa.text("'warning'"), nullable=False),
        *_times("updated_at"),
        sa.CheckConstraint("id = 1", name="notification_email_id_check"),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name="notification_email_port_check"),
        sa.CheckConstraint("security IN ('starttls', 'tls', 'none')", name="notification_email_security_check"),
        sa.CheckConstraint("cardinality(extra_addresses) <= 20", name="notification_email_extra_addresses_check"),
        sa.CheckConstraint("min_severity IN ('warning', 'critical')", name="notification_email_min_severity_check"),
        sa.CheckConstraint(
            "NOT enabled OR (host IS NOT NULL AND from_address IS NOT NULL)", name="notification_email_ready_check"
        ),
        sa.PrimaryKeyConstraint("id", name="notification_email_pkey"),
    )
    op.execute("INSERT INTO notification_email (id) VALUES (1)")

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        # NULL is the email delivery.
        sa.Column("channel_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        *_times("created_at"),
        sa.CheckConstraint("state IN ('pending', 'delivered', 'failed')", name="notification_deliveries_state_check"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["alert_events.id"], ondelete="CASCADE", name="notification_deliveries_event_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["notification_channels.id"],
            ondelete="CASCADE",
            name="notification_deliveries_channel_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="notification_deliveries_pkey"),
        # One delivery per event and channel, and one email per event.
        sa.UniqueConstraint(
            "event_id",
            "channel_id",
            name="notification_deliveries_event_channel_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "notification_deliveries_due_idx",
        "notification_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_index("notification_deliveries_channel_id_idx", "notification_deliveries", ["channel_id"])

    op.add_column("users", sa.Column("alerts_seen_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON alert_rules TO {API}")
    op.execute(f"GRANT SELECT ON alerts, alert_events TO {API}")
    # The sender claims an event FOR UPDATE and marks it dispatched: no other column of it.
    op.execute(f"GRANT UPDATE (dispatched_at) ON alert_events TO {API}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON notification_channels, notification_deliveries TO {API}")
    op.execute(f"GRANT SELECT, UPDATE ON notification_email TO {API}")
    # The collector evaluates the rules and writes the alerts with their events. It never reads the channel tables.
    op.execute(f"GRANT SELECT ON alert_rules TO {COLLECTOR}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON alerts TO {COLLECTOR}")
    op.execute(f"GRANT INSERT ON alert_events TO {COLLECTOR}")


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("notification_email")
    op.drop_table("notification_channels")
    op.drop_table("alert_events")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
    op.drop_column("users", "alerts_seen_at")

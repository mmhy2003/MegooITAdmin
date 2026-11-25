"""collector: the collector's role, the sample interval of each server and the monitoring state

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLLECTOR = "megooitadmin_collector"
# reason IN (…) is NULL when reason is NULL, and a check passes on NULL: IS NOT NULL makes it refuse.
STATE_CHECK = (
    "(state = 'reachable' AND reason IS NULL)"
    " OR (state = 'unreachable' AND reason IS NOT NULL"
    " AND reason IN ('unreachable', 'key_refused', 'ssh_error', 'no_samples'))"
    " OR (state = 'not_monitored' AND reason IS NOT NULL"
    " AND reason IN ('not_an_ssh_server', 'host_key_not_pinned', 'host_key_changed'))"
)


def upgrade() -> None:
    # Like megooitadmin_api (0003): LOGIN and the password come from the entrypoint, from DATABASE_COLLECTOR_URL.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{COLLECTOR}') THEN
                CREATE ROLE {COLLECTOR} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.add_column(
        "servers", sa.Column("metrics_interval_seconds", sa.SmallInteger(), server_default=sa.text("5"), nullable=False)
    )
    op.create_check_constraint(
        "servers_metrics_interval_seconds_check", "servers", "metrics_interval_seconds BETWEEN 1 AND 10"
    )
    op.create_table(
        "server_status",
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("since", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_sample_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(STATE_CHECK, name="server_status_state_check"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="server_status_server_id_fkey"),
        sa.PrimaryKeyConstraint("server_id", name="server_status_pkey"),
    )
    op.execute("GRANT SELECT ON server_status TO megooitadmin_api")

    op.execute(f"GRANT USAGE ON SCHEMA public TO {COLLECTOR}")
    op.execute(f"GRANT INSERT ON metrics TO {COLLECTOR}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON server_status TO {COLLECTOR}")
    # It reads the servers, and flags a changed host key (open_connection): FOR UPDATE needs UPDATE on one column.
    op.execute(f"GRANT SELECT ON servers TO {COLLECTOR}")
    op.execute(f"GRANT UPDATE (host_key_changed_at, host_key_offered, host_key_offered_at) ON servers TO {COLLECTOR}")
    # The audit writer, for server.host_key_mismatch.
    op.execute(f"GRANT INSERT ON audit_log TO {COLLECTOR}")
    op.execute(f"GRANT SELECT, UPDATE ON audit_chain_head TO {COLLECTOR}")


def downgrade() -> None:
    op.drop_table("server_status")
    op.drop_constraint("servers_metrics_interval_seconds_check", "servers", type_="check")
    op.drop_column("servers", "metrics_interval_seconds")
    op.execute(f"DROP OWNED BY {COLLECTOR}")
    op.execute(f"DROP ROLE {COLLECTOR}")

"""checks: the last result of each slow check, and the containers of each server

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLLECTOR = "megooitadmin_collector"


def upgrade() -> None:
    op.create_table(
        "server_checks",
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
        sa.Column("data_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('containers', 'processes', 'services', 'logins', 'updates', 'certificates')",
            name="server_checks_kind_check",
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'not_available', 'denied', 'timeout', 'failed')", name="server_checks_status_check"
        ),
        sa.CheckConstraint("(data IS NULL) = (data_at IS NULL)", name="server_checks_data_check"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="server_checks_server_id_fkey"),
        sa.PrimaryKeyConstraint("server_id", "kind", name="server_checks_pkey"),
    )
    op.create_table(
        "containers",
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("runtime", sa.Text(), nullable=False),
        sa.Column("container_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("image", sa.Text(), nullable=False),
        sa.Column("compose_project", sa.Text(), nullable=True),
        sa.Column("compose_service", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("runtime = 'docker'", name="containers_runtime_check"),
        sa.CheckConstraint(
            "state IN ('created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead', 'unknown')",
            name="containers_state_check",
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="containers_server_id_fkey"),
        sa.PrimaryKeyConstraint("server_id", "runtime", "container_id", name="containers_pkey"),
    )
    # Written by the collector, read by the server API.
    op.execute("GRANT SELECT ON server_checks, containers TO megooitadmin_api")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON server_checks TO {COLLECTOR}")
    # A container Docker no longer lists is deleted at the next successful check.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON containers TO {COLLECTOR}")


def downgrade() -> None:
    op.drop_table("containers")
    op.drop_table("server_checks")

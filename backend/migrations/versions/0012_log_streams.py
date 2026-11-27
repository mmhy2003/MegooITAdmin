"""log streams: the per-group log file allowlist and the logs worker's role

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API = "megooitadmin_api"
LOGS = "megooitadmin_logs"
# app.logs.allowlist.STARTER_PATTERNS when this migration was written. An Admin can remove them.
STARTER_PATTERNS = ("/var/log/syslog", "/var/log/messages", "/var/log/nginx/*.log", "/var/log/apache2/*.log")


def upgrade() -> None:
    # Like megooitadmin_collector (0009): LOGIN and the password come from the entrypoint, from DATABASE_LOGS_URL.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{LOGS}') THEN
                CREATE ROLE {LOGS} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.create_table(
        "log_file_allowlist",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_group_id", sa.Uuid(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(pattern) BETWEEN 2 AND 255", name="log_file_allowlist_pattern_check"),
        sa.ForeignKeyConstraint(
            ["server_group_id"],
            ["server_groups.id"],
            ondelete="CASCADE",
            name="log_file_allowlist_server_group_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="log_file_allowlist_pkey"),
        sa.UniqueConstraint("server_group_id", "pattern", name="log_file_allowlist_server_group_id_pattern_key"),
    )
    patterns = ", ".join(f"('{pattern}')" for pattern in STARTER_PATTERNS)
    op.execute(
        "INSERT INTO log_file_allowlist (id, server_group_id, pattern)"
        f" SELECT gen_random_uuid(), g.id, p.pattern FROM server_groups g CROSS JOIN (VALUES {patterns}) AS p(pattern)"
    )

    op.execute(f"GRANT SELECT, INSERT, DELETE ON log_file_allowlist TO {API}")

    op.execute(f"GRANT USAGE ON SCHEMA public TO {LOGS}")
    # It checks each request again: the server, the container, the path against the group's allowlist.
    op.execute(f"GRANT SELECT ON servers, containers, log_file_allowlist TO {LOGS}")
    # It flags a changed host key (open_connection): FOR UPDATE needs UPDATE on one column.
    op.execute(f"GRANT UPDATE (host_key_changed_at, host_key_offered, host_key_offered_at) ON servers TO {LOGS}")
    # The audit writer, for server.host_key_mismatch.
    op.execute(f"GRANT INSERT ON audit_log TO {LOGS}")
    op.execute(f"GRANT SELECT, UPDATE ON audit_chain_head TO {LOGS}")


def downgrade() -> None:
    op.drop_table("log_file_allowlist")
    op.execute(f"DROP OWNED BY {LOGS}")
    op.execute(f"DROP ROLE {LOGS}")

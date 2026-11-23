"""audit log: the append-only, hash-chained audit_log hypertable and the head of its chain

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("seq", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("actor_name", sa.Text(), nullable=False),
        sa.Column(
            "actor_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("on_behalf_of_id", sa.Text(), nullable=True),
        sa.Column("on_behalf_of_name", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("target_name", sa.Text(), nullable=True),
        sa.Column(
            "context", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("source_ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("auth_method", sa.Text(), nullable=True),
        sa.Column("mfa", sa.Boolean(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("change", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("result_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_class", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("hash", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("actor_type IN ('human', 'agent', 'system')", name="audit_log_actor_type_check"),
        sa.CheckConstraint(r"action ~ '^[a-z0-9_]+(\.[a-z0-9_]+)+$'", name="audit_log_action_check"),
        sa.CheckConstraint("result IN ('success', 'failure', 'error')", name="audit_log_result_check"),
        sa.CheckConstraint(
            "risk_class IN ('platform_read', 'server_read', 'change', 'destructive', 'forbidden')",
            name="audit_log_risk_class_check",
        ),
        sa.CheckConstraint(
            "octet_length(prev_hash) = 32 AND octet_length(hash) = 32", name="audit_log_hash_length_check"
        ),
        sa.PrimaryKeyConstraint("seq", "time", name="audit_log_pkey"),
    )
    op.create_index("audit_log_time_idx", "audit_log", [sa.text("time DESC")])
    # create_default_indexes => false: the model declares every index, so autogenerate stays quiet.
    op.execute(
        "SELECT create_hypertable('audit_log', by_range('time', INTERVAL '30 days'), create_default_indexes => false)"
    )

    op.create_table(
        "audit_chain_head",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("hash", sa.LargeBinary(), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="audit_chain_head_id_check"),
        sa.PrimaryKeyConstraint("id", name="audit_chain_head_pkey"),
    )
    op.execute(
        "INSERT INTO audit_chain_head (id, seq, hash, time) VALUES (1, 0, decode(repeat('00', 32), 'hex'), NULL)"
    )

    op.execute(
        """
        CREATE FUNCTION audit_refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_refuse_change BEFORE UPDATE OR DELETE ON audit_log"
        " FOR EACH ROW EXECUTE FUNCTION audit_refuse_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_refuse_truncate BEFORE TRUNCATE ON audit_log"
        " FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_change()"
    )
    # UPDATE stays allowed on the head: the writer moves it.
    op.execute(
        "CREATE TRIGGER audit_chain_head_refuse_delete BEFORE DELETE ON audit_chain_head"
        " FOR EACH ROW EXECUTE FUNCTION audit_refuse_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_chain_head_refuse_truncate BEFORE TRUNCATE ON audit_chain_head"
        " FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_change()"
    )


def downgrade() -> None:
    op.drop_table("audit_chain_head")
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION audit_refuse_change()")

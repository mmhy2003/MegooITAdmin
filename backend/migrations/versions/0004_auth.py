"""auth: accounts, sessions, recovery codes and the setup code

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-23 16:56:55.205229
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_owner", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("totp_secret", sa.LargeBinary(), nullable=True),
        sa.Column("totp_pending_secret", sa.LargeBinary(), nullable=True),
        sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("email = lower(email)", name="users_email_lower_check"),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
        sa.UniqueConstraint("email", name="users_email_key"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("mfa_method", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.CheckConstraint("stage IN ('pending', 'active')", name="auth_sessions_stage_check"),
        sa.CheckConstraint("mfa_method IN ('totp', 'recovery_code')", name="auth_sessions_mfa_method_check"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="auth_sessions_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="auth_sessions_pkey"),
        sa.UniqueConstraint("token_hash", name="auth_sessions_token_hash_key"),
    )
    op.create_index("auth_sessions_user_id_idx", "auth_sessions", ["user_id"])

    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="recovery_codes_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="recovery_codes_pkey"),
        sa.UniqueConstraint("code_hash", name="recovery_codes_code_hash_key"),
    )
    op.create_index("recovery_codes_user_id_idx", "recovery_codes", ["user_id"])

    op.create_table(
        "auth_setup",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="auth_setup_id_check"),
        sa.PrimaryKeyConstraint("id", name="auth_setup_pkey"),
    )

    # Accounts are never deleted through the API: only the host commands, as the owner, may do that.
    op.execute("GRANT SELECT, INSERT, UPDATE ON users TO megooitadmin_api")
    # Sign-out deletes sessions, using a recovery code deletes it, and claiming the install deletes the setup code.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON auth_sessions, recovery_codes, auth_setup TO megooitadmin_api")


def downgrade() -> None:
    op.drop_table("recovery_codes")
    op.drop_table("auth_sessions")
    op.drop_table("auth_setup")
    op.drop_table("users")

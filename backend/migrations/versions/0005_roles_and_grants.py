"""roles, per-group grants, server groups and invites

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    roles = op.create_table(
        "roles",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("scope IN ('platform', 'group')", name="roles_scope_check"),
        sa.PrimaryKeyConstraint("key", name="roles_pkey"),
    )
    op.bulk_insert(
        roles,
        [
            {"key": "owner", "name": "Owner", "scope": "platform", "position": 1},
            {"key": "admin", "name": "Admin", "scope": "group", "position": 2},
            {"key": "operator", "name": "Operator", "scope": "group", "position": 3},
            {"key": "auditor", "name": "Auditor", "scope": "platform", "position": 4},
        ],
    )

    op.add_column("users", sa.Column("platform_role", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("users_platform_role_fkey", "users", "roles", ["platform_role"], ["key"])
    op.create_check_constraint("users_platform_role_check", "users", "platform_role IN ('owner', 'auditor')")
    # An invited account has no password until its link is used.
    op.alter_column("users", "password_hash", nullable=True)
    op.execute("UPDATE users SET platform_role = 'owner' WHERE is_owner")
    op.drop_column("users", "is_owner")

    op.create_table(
        "server_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="server_groups_pkey"),
    )
    op.create_index("server_groups_name_key", "server_groups", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "role_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("server_group_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        *(
            sa.Column(name, sa.Boolean(), server_default=sa.text("false"), nullable=False)
            for name in ("connect_ssh", "connect_rdp", "view_logs", "view_processes",
                         "manage_processes", "run_playbooks", "manage_playbooks")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'operator')", name="role_grants_role_check"),
        # PRD §14.1: an Operator never manages playbooks.
        sa.CheckConstraint("role = 'admin' OR NOT manage_playbooks", name="role_grants_manage_playbooks_check"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="role_grants_user_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["server_group_id"], ["server_groups.id"], name="role_grants_server_group_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role"], ["roles.key"], name="role_grants_role_fkey"),
        sa.PrimaryKeyConstraint("id", name="role_grants_pkey"),
        sa.UniqueConstraint("user_id", "server_group_id", name="role_grants_user_id_server_group_id_key"),
    )
    op.create_index("role_grants_server_group_id_idx", "role_grants", ["server_group_id"])

    op.create_table(
        "user_invites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="user_invites_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="user_invites_pkey"),
        sa.UniqueConstraint("token_hash", name="user_invites_token_hash_key"),
    )

    op.execute("GRANT SELECT ON roles TO megooitadmin_api")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON server_groups, role_grants, user_invites TO megooitadmin_api")


def downgrade() -> None:
    op.drop_table("user_invites")
    op.drop_table("role_grants")
    op.drop_table("server_groups")
    op.add_column("users", sa.Column("is_owner", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.execute("UPDATE users SET is_owner = coalesce(platform_role = 'owner', false)")
    # '!' is no Argon2 hash, so no password matches an account that never had one.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", nullable=False)
    op.drop_constraint("users_platform_role_check", "users", type_="check")
    op.drop_constraint("users_platform_role_fkey", "users", type_="foreignkey")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "platform_role")
    op.drop_table("roles")

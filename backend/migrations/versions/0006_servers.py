"""servers and server tags

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("os", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("host_key", sa.Text(), nullable=True),
        sa.Column(
            "connection_settings",
            postgresql.JSONB(),
            server_default=sa.text("""'{"username": "megoo"}'::jsonb"""),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name="servers_port_check"),
        sa.CheckConstraint("os IN ('linux', 'windows')", name="servers_os_check"),
        # No cascade: a group that holds servers cannot be deleted.
        sa.ForeignKeyConstraint(["server_group_id"], ["server_groups.id"], name="servers_server_group_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="servers_pkey"),
    )
    op.create_index("servers_name_key", "servers", [sa.text("lower(name)")], unique=True)
    op.create_index("servers_server_group_id_idx", "servers", ["server_group_id"])

    op.create_table(
        "server_tags",
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.CheckConstraint("tag = lower(tag) AND char_length(tag) BETWEEN 1 AND 32", name="server_tags_tag_check"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name="server_tags_server_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("server_id", "tag", name="server_tags_pkey"),
    )
    op.create_index("server_tags_tag_idx", "server_tags", ["tag"])

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON servers, server_tags TO megooitadmin_api")


def downgrade() -> None:
    op.drop_table("server_tags")
    op.drop_table("servers")

"""log views: a person's saved views of the log viewer, private or shared

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API = "megooitadmin_api"


def upgrade() -> None:
    op.create_table(
        "log_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("shared", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="log_views_name_check"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE", name="log_views_owner_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="log_views_pkey"),
    )
    # A person's view names are unique without regard to case.
    op.create_index("log_views_owner_id_name_key", "log_views", ["owner_id", sa.text("lower(name)")], unique=True)

    # A person saves, replaces and deletes their own views; the Owner any shared one.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON log_views TO {API}")


def downgrade() -> None:
    op.drop_table("log_views")

"""host key pinning

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("host_key_pinned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("servers", sa.Column("host_key_offered", sa.Text(), nullable=True))
    op.add_column("servers", sa.Column("host_key_offered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("servers", sa.Column("host_key_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "servers_host_key_pinned_check", "servers", "(host_key IS NULL) = (host_key_pinned_at IS NULL)"
    )
    op.create_check_constraint(
        "servers_host_key_changed_check", "servers", "host_key_changed_at IS NULL OR host_key IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint("servers_host_key_changed_check", "servers", type_="check")
    op.drop_constraint("servers_host_key_pinned_check", "servers", type_="check")
    op.drop_column("servers", "host_key_changed_at")
    op.drop_column("servers", "host_key_offered_at")
    op.drop_column("servers", "host_key_offered")
    op.drop_column("servers", "host_key_pinned_at")

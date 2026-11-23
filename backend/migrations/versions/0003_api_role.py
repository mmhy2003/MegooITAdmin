"""api role: megooitadmin_api, the restricted role the backend serves as

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Roles belong to the cluster, not the database, so another database of the cluster may have created it.
    # LOGIN and the password come from the entrypoint (app.core.db_roles), never from a migration.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'megooitadmin_api') THEN
                CREATE ROLE megooitadmin_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO megooitadmin_api")
    # Append-only by privilege. A chunk takes the hypertable's grants.
    op.execute("GRANT SELECT, INSERT ON audit_log TO megooitadmin_api")
    # The writer locks the head (FOR UPDATE needs UPDATE) and moves it.
    op.execute("GRANT SELECT, UPDATE ON audit_chain_head TO megooitadmin_api")


def downgrade() -> None:
    op.execute("DROP OWNED BY megooitadmin_api")
    op.execute("DROP ROLE megooitadmin_api")

"""A revision that always fails. tests/test_container.py mounts it into migrations/versions/ of a one-off container,
to prove that the container refuses to serve when a migration fails. Never copy it into migrations/versions/."""

from pathlib import Path

from alembic import op  # noqa: F401

revision = "9999"
# The real head: the highest-numbered revision beside this file once it is mounted.
down_revision = max(
    path.name[:4] for path in Path(__file__).parent.glob("[0-9][0-9][0-9][0-9]_*.py") if path.name != "9999_fails.py"
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    raise RuntimeError("9999_fails: this migration fails on purpose")


def downgrade() -> None:
    pass

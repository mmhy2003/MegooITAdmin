"""Shared helpers of the log tests: allowlist patterns."""

from uuid import UUID

from conftest import owner_session

from app.logs.models import LogFileAllowlist


async def add_pattern(group_id: UUID, pattern: str) -> None:
    """Inserts a log_file_allowlist row as the owner, without events."""
    async with owner_session() as session:
        session.add(LogFileAllowlist(server_group_id=group_id, pattern=pattern))
        await session.commit()

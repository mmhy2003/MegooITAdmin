"""Shared helpers of the log tests: allowlist patterns and log files."""

from uuid import UUID, uuid4

from conftest import owner_session

from app.logs.models import LogFileAllowlist


async def add_pattern(group_id: UUID, pattern: str) -> None:
    """Inserts a log_file_allowlist row as the owner, without events."""
    async with owner_session() as session:
        session.add(LogFileAllowlist(server_group_id=group_id, pattern=pattern))
        await session.commit()


def log_file(name: str) -> str:
    """A path of its own on the fake server, which the starter patterns cover."""
    return f"/var/log/nginx/{name}-{uuid4().hex[:8]}.log"

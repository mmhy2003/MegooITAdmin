"""The current time for auth code.

Auth code calls clock.now() through the module (from app.auth import clock), never datetime.now, so the
tests can replace it with a fake clock.
"""

from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)

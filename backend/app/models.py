"""Every model module is imported here, so that Alembic sees all tables on Base.metadata."""

import app.audit.models  # noqa: F401
import app.auth.models  # noqa: F401

"""Every model module is imported here, so that Alembic sees all tables on Base.metadata."""

import app.access.models  # noqa: F401
import app.audit.models  # noqa: F401
import app.auth.models  # noqa: F401
import app.checks.models  # noqa: F401
import app.inventory.models  # noqa: F401
import app.metrics.models  # noqa: F401
import app.users.models  # noqa: F401

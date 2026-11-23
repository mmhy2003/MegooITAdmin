"""The API role megooitadmin_api: the backend serves as it, and the entrypoint gives it its password.

Migration 0003 creates the role without login. `python -m app.core.db_roles` runs after `alembic upgrade head`, as
the owner, and gives the role LOGIN and the password of DATABASE_URL. The password is sent as a SCRAM-SHA-256
verifier, as psql's \\password does, so the plain password never reaches the database or its log."""

API_ROLE = "megooitadmin_api"

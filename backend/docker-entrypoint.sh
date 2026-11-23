#!/bin/sh
# Applies every pending migration and sets the API role's password, both as the owner (DATABASE_OWNER_URL), then
# starts the server as megooitadmin_api (DATABASE_URL). Run one backend replica: two that start together would
# migrate at the same time.
set -e

# Stop before anything runs: the key encrypts the authenticator secrets, so a backend without it cannot check a code.
: "${AUTH_SECRET_KEY:?AUTH_SECRET_KEY is not set: run make up, or see .env.example}"

echo "Applying database migrations..."
alembic upgrade head

echo "Setting the password of the API role..."
python -m app.core.db_roles

# On a fresh install every start logs a new code, which replaces the last one. Once an account exists, this says nothing.
echo "Checking for a setup code..."
python -m app.auth.cli setup-code --if-no-account

# The server never holds the owner's password. docker compose exec still gets it (make migrate).
unset DATABASE_OWNER_URL
exec "$@"

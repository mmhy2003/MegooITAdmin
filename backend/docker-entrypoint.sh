#!/bin/sh
# Applies every pending migration, then starts the server. Run one backend replica: two that start
# together would migrate at the same time.
set -e

echo "Applying database migrations..."
alembic upgrade head

exec "$@"

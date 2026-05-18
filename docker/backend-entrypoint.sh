#!/bin/sh
set -e

# Wait for Postgres to accept connections. healthcheck on the compose side
# already gates startup, but this gives a clean error if compose is bypassed.
host="${POSTGRES_HOST:-postgres}"
port="${POSTGRES_PORT:-5432}"
attempts=30
while ! python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('${host}', ${port}))" 2>/dev/null; do
  attempts=$((attempts - 1))
  if [ "$attempts" -le 0 ]; then
    echo "postgres @ ${host}:${port} unreachable after 30s; aborting" >&2
    exit 1
  fi
  sleep 1
done

echo "applying alembic migrations..."
alembic upgrade head

exec "$@"

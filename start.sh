#!/usr/bin/env bash

# Development bootstrap script -------------------------------------------------
# 1. Optionally start the Redis service (via docker-compose) so the API can
#    connect locally without manual setup.
# 2. Launch FastAPI with hot-reload, excluding the tests directory.
# -----------------------------------------------------------------------------

set -e

# By default we spin up redis using docker-compose. Set SKIP_REDIS=true to skip.
if [[ "${SKIP_REDIS:-false}" != "true" ]]; then
  # Only attempt if docker-compose is available
  if command -v docker compose &>/dev/null; then
    echo "Ensuring Redis service is running …"
    # 'docker compose ps' returns non-zero if the service is not created yet
    if ! docker compose ps redis &>/dev/null; then
      docker compose up -d redis
    else
      # If the container exists but is stopped, start it
      docker compose start redis &>/dev/null || true
    fi
  else
    echo "docker compose not found; skipping automatic Redis startup." >&2
  fi
fi

# If no REDIS_URL is set, default to localhost (works with the redis container
# started above).  This affects only the current shell invocation, not your
# global environment.
if [[ -z "${REDIS_URL}" ]]; then
  export REDIS_URL="redis://localhost:6379/0"
  echo "REDIS_URL not set – defaulting to ${REDIS_URL}"
fi

echo "Starting FastAPI application..."
./venv/bin/python -m uvicorn app.main:app \
  --workers 4 \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8000}"


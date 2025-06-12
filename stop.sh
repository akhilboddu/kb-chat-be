#!/usr/bin/env bash

# -----------------------------------------------------------------------------
# stop.sh  –  Convenience script for local development
# Stops:
#   1. Any running Uvicorn process that was started via start.sh (or manually)
#      and serves app.main:app.
#   2. The Redis service started through docker-compose (if available).
# -----------------------------------------------------------------------------

set -e

echo "Stopping FastAPI (uvicorn app.main:app) if running …"
# `pkill -f` exits with code 1 if nothing matched; we ignore that.
pkill -f "uvicorn.*app\.main:app" 2>/dev/null || true

if command -v docker compose &>/dev/null; then
  echo "Stopping Redis docker-compose service …"
  # Stop but do not remove the container so it can start quickly next time.
  docker compose stop redis 2>/dev/null || true
else
  echo "docker compose not found; skipping Redis container shutdown." >&2
fi

echo "✅ All local services stopped." 
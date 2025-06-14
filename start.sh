#!/usr/bin/env bash

# Development bootstrap script -------------------------------------------------
# 1. Optionally start the Redis service (via docker-compose) so the API can
#    connect locally without manual setup.
# 2. Optionally start Celery workers if START_CELERY=true
# 3. Launch FastAPI with hot-reload, excluding the tests directory.
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

# Set Celery environment variables if not already set
if [[ -z "${CELERY_BROKER_URL}" ]]; then
  export CELERY_BROKER_URL="${REDIS_URL}"
  echo "CELERY_BROKER_URL not set – defaulting to ${CELERY_BROKER_URL}"
fi

if [[ -z "${CELERY_RESULT_BACKEND}" ]]; then
  export CELERY_RESULT_BACKEND="redis://localhost:6379/1"
  echo "CELERY_RESULT_BACKEND not set – defaulting to ${CELERY_RESULT_BACKEND}"
fi

# Optionally start Celery workers
if [[ "${START_CELERY:-false}" == "true" ]]; then
  if [[ "${CELERY_MODE:-docker}" == "docker" ]]; then
    # Start Celery workers via Docker Compose
    if command -v docker compose &>/dev/null; then
      echo "Starting Celery workers via Docker Compose..."
      docker compose up -d celery-worker-scrape celery-worker-upload
      
      # Optionally start Flower for monitoring
      if [[ "${START_FLOWER:-false}" == "true" ]]; then
        echo "Starting Flower monitoring dashboard..."
        docker compose up -d flower
      fi
    else
      echo "docker compose not found; skipping Docker Celery worker startup." >&2
    fi
  else
    # Start Celery workers directly
    echo "Starting Celery workers directly..."
    
    # Start scrape worker in background
    echo "Starting scrape worker..."
    ./venv/bin/celery -A app.worker.celery_app worker -Q scrape --loglevel=info &
    SCRAPE_WORKER_PID=$!
    echo "Scrape worker started with PID: $SCRAPE_WORKER_PID"
    
    # Start upload worker in background  
    echo "Starting upload worker..."
    ./venv/bin/celery -A app.worker.celery_app worker -Q upload --loglevel=info &
    UPLOAD_WORKER_PID=$!
    echo "Upload worker started with PID: $UPLOAD_WORKER_PID"
    
    # Optionally start Flower for monitoring
    if [[ "${START_FLOWER:-false}" == "true" ]]; then
      echo "Starting Flower monitoring dashboard..."
      ./venv/bin/celery -A app.worker.celery_app flower --port=5555 &
      FLOWER_PID=$!
      echo "Flower started with PID: $FLOWER_PID at http://localhost:5555"
    fi
    
    # Store PIDs for cleanup
    echo "$SCRAPE_WORKER_PID" > .celery_scrape_worker.pid
    echo "$UPLOAD_WORKER_PID" > .celery_upload_worker.pid
    [[ -n "$FLOWER_PID" ]] && echo "$FLOWER_PID" > .celery_flower.pid
    
    # Function to cleanup workers on exit
    cleanup_workers() {
      echo "Stopping Celery workers..."
      [[ -f .celery_scrape_worker.pid ]] && kill $(cat .celery_scrape_worker.pid) 2>/dev/null || true
      [[ -f .celery_upload_worker.pid ]] && kill $(cat .celery_upload_worker.pid) 2>/dev/null || true  
      [[ -f .celery_flower.pid ]] && kill $(cat .celery_flower.pid) 2>/dev/null || true
      rm -f .celery_*.pid
    }
    
    # Setup cleanup on script exit
    trap cleanup_workers EXIT
  fi
fi

# Auto-tune Uvicorn workers if not overridden
if [[ -z "${UVICORN_WORKERS}" ]]; then
  CPU_CORES=$(./venv/bin/python - <<'PY'
import multiprocessing, os, math
cores = multiprocessing.cpu_count()
print(max(2, min(8, (cores * 2) + 1)))
PY
)
  export UVICORN_WORKERS=$CPU_CORES
  echo "Auto-detected CPU cores: $(./venv/bin/python -c 'import multiprocessing; print(multiprocessing.cpu_count())')"
  echo "Setting UVICORN_WORKERS=${UVICORN_WORKERS}"
fi

echo "Starting FastAPI application..."
./venv/bin/python -m uvicorn app.main:app \
  --workers ${UVICORN_WORKERS} \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8000}"


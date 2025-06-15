#!/bin/bash

# KB Chat Backend Startup Script
# Supports both development and production environments

set -e  # Exit on any error

echo "🚀 Starting KB Chat Backend..."

# ------------------------------------------------------------------
# Load environment variables from .env if present so users don't need
# to `export` them manually every time.
# ------------------------------------------------------------------
if [[ -f .env ]]; then
    echo "🔑 Loading environment variables from .env"
    # shellcheck disable=SC2163
    export $(grep -v '^#' .env | xargs)
fi

# Function to check if a process is running
is_running() {
    pgrep -f "$1" > /dev/null
}

# Function to stop existing processes
stop_existing() {
    echo "🔄 Stopping existing processes..."
    
    # Stop existing FastAPI server
    if is_running "uvicorn.*main:app"; then
        echo "Stopping existing FastAPI server..."
        pkill -f "uvicorn.*main:app" || true
    fi
    
    # Stop existing Celery workers
    if is_running "celery.*worker"; then
        echo "Stopping existing Celery workers..."
        pkill -f "celery.*worker" || true
    fi
    
    # Stop existing Flower
    if is_running "celery.*flower"; then
        echo "Stopping existing Flower..."
        pkill -f "celery.*flower" || true
    fi
    
    sleep 2
}

# Check if virtual environment exists
if [[ ! -d "venv" ]]; then
    echo "❌ Virtual environment not found. Creating one..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "📦 Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
if [[ ! -f "venv/.deps_installed" ]] || [[ requirements.txt -nt venv/.deps_installed ]]; then
    echo "📚 Installing/updating dependencies..."
    pip install -r requirements.txt
    touch venv/.deps_installed
fi

# Set default environment variables
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Check for required environment variables
if [[ -z "${SUPABASE_URL}" ]]; then
    echo "⚠️  SUPABASE_URL not set in environment"
fi

if [[ -z "${REDIS_URL}" ]]; then
    export REDIS_URL="redis://localhost:6379/0"
    echo "REDIS_URL not set – defaulting to ${REDIS_URL}"
fi

if [[ -z "${CELERY_BROKER_URL}" ]]; then
    export CELERY_BROKER_URL="${REDIS_URL}"
    echo "CELERY_BROKER_URL not set – defaulting to ${CELERY_BROKER_URL}"
fi

if [[ -z "${CELERY_RESULT_BACKEND}" ]]; then
    export CELERY_RESULT_BACKEND="redis://localhost:6379/1"
    echo "CELERY_RESULT_BACKEND not set – defaulting to ${CELERY_RESULT_BACKEND}"
fi

# Stop existing processes
stop_existing

# Check if Redis is running
if ! redis-cli ping >/dev/null 2>&1; then
    echo "⚠️  Local Redis is not running. Checking Docker Redis..."
    if docker ps | grep -q redis; then
        echo "✅ Docker Redis is running"
    else
        echo "❌ Neither local Redis nor Docker Redis is running"
        echo "Please ensure Redis is running either locally or in Docker"
        exit 1
    fi
fi

# Optionally start Celery workers
if [[ "${START_CELERY:-false}" == "true" ]]; then
    echo "🔧 Starting Celery workers..."
    
    # Check if workers are already running
    if is_running "celery.*worker.*-Q scrape"; then
        echo "Scrape worker is already running, skipping..."
    else
        # Start scrape worker in background
        echo "Starting scrape worker..."
        ./venv/bin/celery -A app.worker.celery_app worker -Q scrape --loglevel=info -n scrape@%h --concurrency=1 &
        SCRAPE_WORKER_PID=$!
        echo "Scrape worker started with PID: $SCRAPE_WORKER_PID"
    fi
    
    if is_running "celery.*worker.*-Q upload"; then
        echo "Upload worker is already running, skipping..."
    else
        # Start upload worker in background
        echo "Starting upload worker..."
        ./venv/bin/celery -A app.worker.celery_app worker -Q upload --loglevel=info -n upload@%h --concurrency=1 &
        UPLOAD_WORKER_PID=$!
        echo "Upload worker started with PID: $UPLOAD_WORKER_PID"
    fi
    
    if is_running "celery.*worker.*-Q optimize"; then
        echo "Optimize worker is already running, skipping..."
    else
        # Start optimize worker in background
        echo "Starting optimize worker..."
        ./venv/bin/celery -A app.worker.celery_app worker -Q optimize --loglevel=info -n optimize@%h --concurrency=1 &
        OPTIMIZE_WORKER_PID=$!
        echo "Optimize worker started with PID: $OPTIMIZE_WORKER_PID"
    fi
    
    # Optionally start Flower for monitoring
    if [[ "${START_FLOWER:-false}" == "true" ]]; then
        echo "🌸 Starting Flower monitoring dashboard..."
        ./venv/bin/celery -A app.worker.celery_app flower --port=5555 &
        FLOWER_PID=$!
        echo "Flower started with PID: $FLOWER_PID at http://localhost:5555"
    fi
    
    # Store PIDs for cleanup
    [[ -n "$SCRAPE_WORKER_PID" ]] && echo "$SCRAPE_WORKER_PID" > .celery_scrape_worker.pid
    [[ -n "$UPLOAD_WORKER_PID" ]] && echo "$UPLOAD_WORKER_PID" > .celery_upload_worker.pid
    [[ -n "$OPTIMIZE_WORKER_PID" ]] && echo "$OPTIMIZE_WORKER_PID" > .celery_optimize_worker.pid
    [[ -n "$FLOWER_PID" ]] && echo "$FLOWER_PID" > .celery_flower.pid
    
    # Function to cleanup workers on exit
    cleanup() {
        echo "🧹 Cleaning up background processes..."
        [[ -n "$SCRAPE_WORKER_PID" ]] && kill $SCRAPE_WORKER_PID 2>/dev/null || true
        [[ -n "$UPLOAD_WORKER_PID" ]] && kill $UPLOAD_WORKER_PID 2>/dev/null || true
        [[ -n "$OPTIMIZE_WORKER_PID" ]] && kill $OPTIMIZE_WORKER_PID 2>/dev/null || true
        [[ -n "$FLOWER_PID" ]] && kill $FLOWER_PID 2>/dev/null || true
        rm -f .celery_*.pid
    }
    
    # Set trap to cleanup on script exit
    trap cleanup EXIT
    
    echo "✅ Celery workers started successfully"
    echo "📊 Monitor at: http://localhost:5555 (if Flower is enabled)"
fi

# Start the FastAPI server
echo "🌐 Starting FastAPI server..."
echo "📍 Server will be available at: http://localhost:8000"
echo "📖 API docs at: http://localhost:8000/docs"
echo "🏥 Health check at: http://localhost:8000/health"

# Use environment variables for configuration
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

if [[ "${ENV:-development}" == "production" ]]; then
    echo "🏭 Starting in production mode..."
    ./venv/bin/uvicorn app.main:app --host $HOST --port $PORT --workers $WORKERS
else
    echo "🔧 Starting in development mode with auto-reload..."
    ./venv/bin/uvicorn app.main:app --host $HOST --port $PORT --reload
fi


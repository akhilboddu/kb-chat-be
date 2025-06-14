#!/usr/bin/env bash

# Script to cleanly stop all Celery workers and optionally Redis
# Usage: ./stop-workers.sh [--all]

echo "Stopping Celery workers..."

# Stop Celery workers gracefully
if pgrep -f "celery.*worker" > /dev/null; then
    echo "Sending TERM signal to Celery workers for graceful shutdown..."
    pkill -TERM -f "celery.*worker"
    
    # Wait up to 10 seconds for graceful shutdown
    for i in {1..10}; do
        if ! pgrep -f "celery.*worker" > /dev/null; then
            echo "All Celery workers stopped gracefully."
            break
        fi
        echo "Waiting for workers to stop... ($i/10)"
        sleep 1
    done
    
    # Force kill if still running
    if pgrep -f "celery.*worker" > /dev/null; then
        echo "Force stopping remaining workers..."
        pkill -9 -f "celery.*worker"
    fi
else
    echo "No Celery workers found running."
fi

# Clean up PID files if they exist
rm -f .celery_*.pid

# Stop Redis if --all flag is provided
if [[ "$1" == "--all" ]]; then
    echo "Stopping Redis..."
    if command -v docker compose &>/dev/null; then
        docker compose stop redis
    fi
fi

echo "Cleanup complete!" 
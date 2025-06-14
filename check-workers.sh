#!/usr/bin/env bash

# Script to check the status of all services

echo "=== Service Status Check ==="
echo

# Check Redis
echo "📦 Redis:"
if docker compose ps redis 2>/dev/null | grep -q "running"; then
    echo "   ✅ Running (Docker)"
elif pgrep -x redis-server > /dev/null; then
    echo "   ✅ Running (Local)"
else
    echo "   ❌ Not running"
fi

# Check API Server
echo
echo "🚀 API Server:"
if pgrep -f "uvicorn.*app.main:app" > /dev/null; then
    API_COUNT=$(pgrep -f "uvicorn.*app.main:app" | wc -l)
    echo "   ✅ Running ($API_COUNT workers)"
else
    echo "   ❌ Not running"
fi

# Check Celery Workers
echo
echo "⚙️  Celery Workers:"

# Check scrape worker
SCRAPE_COUNT=$(pgrep -f "celery.*worker.*-Q scrape" | wc -l)
if [ $SCRAPE_COUNT -gt 0 ]; then
    echo "   ✅ Scrape worker: Running ($SCRAPE_COUNT processes)"
else
    echo "   ❌ Scrape worker: Not running"
fi

# Check upload worker
UPLOAD_COUNT=$(pgrep -f "celery.*worker.*-Q upload" | wc -l)
if [ $UPLOAD_COUNT -gt 0 ]; then
    echo "   ✅ Upload worker: Running ($UPLOAD_COUNT processes)"
else
    echo "   ❌ Upload worker: Not running"
fi

# Check for duplicate workers warning
TOTAL_CELERY=$(pgrep -f "celery.*worker" | wc -l)
if [ $TOTAL_CELERY -gt 20 ]; then
    echo "   ⚠️  WARNING: Too many Celery processes ($TOTAL_CELERY)! Run ./stop-workers.sh to clean up."
fi

# Check Flower (if enabled)
if pgrep -f "celery.*flower" > /dev/null; then
    echo "   ✅ Flower monitoring: Running (http://localhost:5555)"
fi

echo
echo "=== Quick Commands ==="
echo "Start all:        ./start.sh"
echo "Stop workers:     ./stop-workers.sh"
echo "Stop everything:  ./stop-workers.sh --all"
echo

# Check for duplicate workers warning
TOTAL_CELERY=$(pgrep -f "celery.*worker" | wc -l)
if [ $TOTAL_CELERY -gt 20 ]; then
    echo "   ⚠️  WARNING: Too many Celery processes ($TOTAL_CELERY)! Run ./stop-workers.sh to clean up."
fi 
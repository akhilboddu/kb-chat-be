#!/bin/bash
# Restart Celery workers to load new code

echo "🔄 Restarting Celery workers..."

# Kill existing workers
echo "Stopping existing workers..."
pkill -f "celery.*worker.*upload"
pkill -f "celery.*worker.*scrape" 
pkill -f "celery.*worker.*optimize"

# Wait for processes to stop
sleep 2

# Start new workers
echo "Starting new workers with updated code..."

# Upload worker with thread pool for ML stability
nohup celery -A app.worker.celery_app worker -Q upload --pool=threads --concurrency=2 --loglevel=info -n upload@%h > celery_upload.log 2>&1 &
echo "✅ Upload worker started with thread pool (PID: $!)"

# Scrape worker with thread pool
nohup celery -A app.worker.celery_app worker -Q scrape --pool=threads --concurrency=2 --loglevel=info -n scrape@%h > celery_scrape.log 2>&1 &
echo "✅ Scrape worker started with thread pool (PID: $!)"

# Optimize worker with thread pool
nohup celery -A app.worker.celery_app worker -Q optimize --pool=threads --concurrency=2 --loglevel=info -n optimize@%h > celery_optimize.log 2>&1 &
echo "✅ Optimize worker started with thread pool (PID: $!)"

echo "🚀 All workers restarted!"
echo "📋 Check logs with: tail -f celery_*.log"
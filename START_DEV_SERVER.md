# Development Server Setup Guide

./venv/bin/python check_connections.py
START_CELERY=true ./start.sh

This guide explains how to start the development server for the Knowledge Base Chat Backend API.

## Prerequisites

1. **Python Virtual Environment**: Ensure you have a Python virtual environment set up
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Dependencies**: Install all required packages
   ```bash
   pip install -r requirements.txt
   ```

3. **Docker**: Required for Redis and optional Celery workers
   ```bash
   # Verify Docker is running
   docker --version
   docker compose --version
   ```

## Quick Start

The simplest way to start the development server:

```bash
./start.sh
```

This will:
- Start Redis automatically via Docker Compose
- Auto-detect CPU cores and set appropriate Uvicorn workers
- Launch the FastAPI application with hot-reload

## Environment Variables

### Required Variables
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_KEY`: Your Supabase service role key
- `ANTHROPIC_API_KEY`: Claude API key for LLM operations
- `COHERE_API_KEY`: Cohere API key for embeddings

### Optional Variables
- `REDIS_URL`: Redis connection URL (default: `redis://localhost:6379/0`)
- `API_HOST`: Host to bind the API server (default: `0.0.0.0`)
- `API_PORT`: Port for the API server (default: `8000`)
- `UVICORN_WORKERS`: Number of Uvicorn workers (auto-detected if not set)

### Celery Configuration
- `START_CELERY`: Set to `true` to start Celery workers (default: `false`)
- `CELERY_MODE`: `docker` or `direct` (default: `docker`)
- `CELERY_BROKER_URL`: Celery broker URL (defaults to `REDIS_URL`)
- `CELERY_RESULT_BACKEND`: Celery result backend (default: `redis://localhost:6379/1`)
- `START_FLOWER`: Set to `true` to start Flower monitoring dashboard (default: `false`)

### Service Control
- `SKIP_REDIS`: Set to `true` to skip automatic Redis startup (default: `false`)
- `USE_CELERY`: Enable/disable Celery task processing (default: `true`)

## Starting with Celery Workers

For background task processing (file uploads, web scraping):

```bash
START_CELERY=true ./start.sh
```

### Celery Modes

#### Docker Mode (Recommended)
```bash
START_CELERY=true CELERY_MODE=docker ./start.sh
```
- Uses Docker Compose to manage workers
- Better resource isolation
- Easier to scale

#### Direct Mode
```bash
START_CELERY=true CELERY_MODE=direct ./start.sh
```
- Runs workers directly in the current environment
- Useful for debugging
- Workers will be cleaned up when script exits

### With Flower Monitoring
```bash
START_CELERY=true START_FLOWER=true ./start.sh
```
- Access Flower dashboard at: http://localhost:5555
- Monitor task queues, worker status, and task history

## Manual Service Management

### Start Only Redis
```bash
docker compose up -d redis
```

### Start Celery Workers Manually
```bash
# Scrape worker
celery -A app.worker.celery_app worker -Q scrape --loglevel=info

# Upload worker (in another terminal)
celery -A app.worker.celery_app worker -Q upload --loglevel=info
```

### Start API Server Only
```bash
# Skip Redis and Celery, just start the API
SKIP_REDIS=true START_CELERY=false ./start.sh
```

## Development Configurations

### Minimal Setup (API only)
```bash
SKIP_REDIS=true START_CELERY=false USE_CELERY=false ./start.sh
```
- No Redis dependency
- No background task processing
- Tasks run synchronously in API process

### Full Development Stack
```bash
START_CELERY=true START_FLOWER=true ./start.sh
```
- Redis for caching and task queue
- Celery workers for background processing
- Flower for monitoring
- Auto-tuned Uvicorn workers

### Production-like Setup
```bash
UVICORN_WORKERS=4 START_CELERY=true CELERY_MODE=docker ./start.sh
```
- Fixed number of API workers
- Containerized Celery workers
- Suitable for staging environments

## Troubleshooting

### Redis Connection Issues
```bash
# Check if Redis is running
docker compose ps redis

# View Redis logs
docker compose logs redis

# Restart Redis
docker compose restart redis
```

### Celery Worker Issues
```bash
# Check worker status
celery -A app.worker.celery_app inspect active

# View worker logs (Docker mode)
docker compose logs celery-worker-scrape
docker compose logs celery-worker-upload

# Check queue status
celery -A app.worker.celery_app inspect reserved
```

### Port Conflicts
If port 8000 is already in use:
```bash
API_PORT=8001 ./start.sh
```

### Memory Issues
Reduce the number of workers:
```bash
UVICORN_WORKERS=2 ./start.sh
```

## Service URLs

When running the full stack:
- **API Server**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Flower Dashboard**: http://localhost:5555 (if enabled)
- **Redis**: localhost:6379

## Performance Tuning

### Worker Configuration
The script auto-detects CPU cores and sets workers as: `max(2, min(8, (cores * 2) + 1))`

| CPU Cores | Auto Workers | Memory Usage |
|-----------|--------------|--------------|
| 1         | 2            | ~300 MB      |
| 2         | 3            | ~450 MB      |
| 4         | 6            | ~900 MB      |
| 8+        | 8 (capped)   | ~1.3 GB      |

### Override Auto-detection
```bash
UVICORN_WORKERS=4 ./start.sh
```

### Celery Worker Concurrency
Each Celery worker runs with 4 concurrent processes by default. This is configured in `docker-compose.yml`:
```yaml
command: celery -A app.worker.celery_app worker -Q scrape -c 4 --loglevel=info
```

## Environment File Example

Create a `.env` file in the project root:
```env
# Required
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
ANTHROPIC_API_KEY=your-claude-api-key
COHERE_API_KEY=your-cohere-api-key

# Optional
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
API_HOST=0.0.0.0
API_PORT=8000

# Development flags
START_CELERY=true
START_FLOWER=true
USE_CELERY=true
```

## Helper Scripts

### Check Service Status
```bash
./check-workers.sh
```
Shows the status of all services (Redis, API, Celery workers) and warns about issues.

### Stop Workers Cleanly
```bash
./stop-workers.sh          # Stop only Celery workers
./stop-workers.sh --all     # Stop Celery workers and Redis
```

### Common Issues & Solutions

#### Too Many Worker Processes
If you see "Too many Celery processes" warning:
```bash
./stop-workers.sh
./start.sh
```

#### Workers Already Running
The updated `start.sh` now checks for existing workers before starting new ones, preventing duplicates.

## Next Steps

1. **Frontend**: Start the React frontend from the `chatbot` directory
2. **Testing**: Run the test suite with `pytest`
3. **Database**: Check Supabase tables are properly set up
4. **Monitoring**: Use Flower dashboard to monitor background tasks

For more details, see the main project documentation and `IMPLEMENTATION_PLAN.md`. 
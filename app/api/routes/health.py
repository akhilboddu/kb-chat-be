from fastapi import APIRouter, HTTPException
from app.utils.task_protection import TaskHealthMonitor, TaskProtection
from app.worker.celery_app import celery_app
import redis
import os
import psutil
from datetime import datetime
from app.utils.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)

@router.get("/health")
async def health_check():
    """Basic health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

@router.get("/health/workers")
async def check_worker_health():
    """
    Check the health of Celery workers and task processing.
    
    Returns:
    - Worker count and status
    - Active task count
    - Queue depths
    - Any warnings or issues
    """
    try:
        health_status = TaskHealthMonitor.check_worker_health()
        
        # Add queue depth information
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        
        queue_info = {}
        for queue_name in ["scrape", "upload"]:
            queue_key = f"celery:queue:{queue_name}"
            queue_depth = redis_client.llen(queue_key)
            queue_info[queue_name] = queue_depth
        
        # Check for stale tasks
        stale_count = 0
        for pattern in ["task:scrape:*", "task:upload:*"]:
            for key in redis_client.scan_iter(match=pattern):
                ttl = redis_client.ttl(key)
                if ttl == -1:  # No expiration
                    stale_count += 1
        
        return {
            **health_status,
            "queues": queue_info,
            "stale_tasks": stale_count,
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
            "timestamp": datetime.utcnow()
        }

@router.post("/health/cleanup")
async def cleanup_tasks():
    """
    Manually trigger cleanup of stale tasks and registrations.
    
    This should be called periodically or when issues are detected.
    """
    try:
        # Clean up stale task registrations
        cleaned = TaskProtection.cleanup_stale_tasks()
        
        # Run additional cleanup
        result = TaskHealthMonitor.auto_cleanup_tasks()
        
        return {
            "status": "success",
            "cleaned_registrations": cleaned,
            "result": result,
            "timestamp": datetime.utcnow()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@router.get("/health/tasks/{kb_id}")
async def check_kb_tasks(kb_id: str):
    """
    Check if any tasks are currently running for a specific knowledge base.
    
    Useful for preventing duplicate operations in the UI.
    """
    try:
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        
        active_tasks = {}
        for task_type in ["scrape", "upload", "optimize"]:
            key_pattern = f"task:{task_type}:{kb_id}*"
            keys = list(redis_client.scan_iter(match=key_pattern))
            if keys:
                task_info = []
                for key in keys:
                    task_id = redis_client.get(key)
                    ttl = redis_client.ttl(key)
                    task_info.append({
                        "task_id": task_id.decode() if task_id else None,
                        "ttl_seconds": ttl
                    })
                active_tasks[task_type] = task_info
        
        return {
            "kb_id": kb_id,
            "active_tasks": active_tasks,
            "has_active_tasks": len(active_tasks) > 0,
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check tasks: {str(e)}")


@router.get("/health/memory")
async def memory_health():
    """Memory usage health check for m5.xlarge monitoring"""
    memory = psutil.virtual_memory()
    status = "healthy" if memory.percent < 85 else "warning"
    
    response = {
        "memory_percent": memory.percent,
        "memory_available_gb": memory.available / (1024**3),
        "memory_total_gb": memory.total / (1024**3),
        "memory_used_gb": memory.used / (1024**3),
        "status": status
    }
    
    # Log warning if memory usage is high
    if status == "warning":
        logger.warning("high_memory_usage", 
                      memory_percent=memory.percent,
                      memory_available_gb=response["memory_available_gb"])
        # Return HTTP 503 if memory usage is critical
        raise HTTPException(status_code=503, detail=response)
    
    return response


@router.get("/health/system")
async def system_health():
    """Comprehensive system health check including CPU, memory, and disk"""
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=1)
    disk = psutil.disk_usage('/')
    
    # Get process-specific memory usage
    process = psutil.Process(os.getpid())
    process_memory_mb = process.memory_info().rss / 1024 / 1024
    
    return {
        "status": "healthy" if memory.percent < 85 and cpu_percent < 90 else "warning",
        "memory": {
            "system_percent": memory.percent,
            "available_gb": memory.available / (1024**3),
            "total_gb": memory.total / (1024**3),
            "used_gb": memory.used / (1024**3),
            "process_memory_mb": process_memory_mb
        },
        "cpu": {
            "percent": cpu_percent,
            "count": psutil.cpu_count(),
            "count_logical": psutil.cpu_count(logical=True)
        },
        "disk": {
            "percent": disk.percent,
            "free_gb": disk.free / (1024**3),
            "total_gb": disk.total / (1024**3)
        },
        "timestamp": datetime.utcnow()
    } 
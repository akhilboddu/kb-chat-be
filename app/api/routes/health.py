from fastapi import APIRouter, HTTPException
from app.utils.task_protection import TaskHealthMonitor, TaskProtection
from app.worker.celery_app import celery_app
import redis
import os
from datetime import datetime

router = APIRouter(tags=["health"])

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
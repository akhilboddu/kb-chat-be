"""
Task Protection Utilities

Provides safeguards against common task-related issues:
- Duplicate task prevention
- Zombie task detection
- Resource limit enforcement
- Automatic cleanup
"""

import os
import time
import redis
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import logging
from functools import wraps

logger = logging.getLogger(__name__)

# Initialize Redis client for task tracking
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


class TaskProtection:
    """Provides protection mechanisms for background tasks"""
    
    # Task timeout settings (in seconds) - reduced to allow retries
    TASK_TIMEOUTS = {
        "scrape": 600,      # 10 minutes
        "upload": 180,      # 3 minutes (reduced from 5)
        "optimize": 900,    # 15 minutes
    }
    
    # Maximum concurrent tasks per type
    MAX_CONCURRENT_TASKS = {
        "scrape": 3,
        "upload": 5,
        "optimize": 1,
    }
    
    @staticmethod
    def check_duplicate_task(task_type: str, kb_id: str, unique_key: str = None) -> bool:
        """
        Check if a similar task is already running for this KB.
        Returns True if duplicate found, False otherwise.
        """
        key = f"task:{task_type}:{kb_id}"
        if unique_key:
            key += f":{unique_key}"
            
        # Check if task key exists and hasn't expired
        existing = redis_client.get(key)
        if existing:
            logger.warning(f"Duplicate {task_type} task detected for KB {kb_id}")
            return True
        return False
    
    @staticmethod
    def register_task(task_type: str, kb_id: str, task_id: str, unique_key: str = None) -> bool:
        """
        Register a new task with automatic expiration.
        Returns True if registered successfully, False if duplicate exists.
        """
        key = f"task:{task_type}:{kb_id}"
        if unique_key:
            key += f":{unique_key}"
            
        # Set with NX (only if not exists) and expiration
        timeout = TaskProtection.TASK_TIMEOUTS.get(task_type, 600)
        success = redis_client.set(
            key, 
            task_id, 
            nx=True,  # Only set if not exists
            ex=timeout  # Expire after timeout
        )
        
        if success:
            logger.info(f"Registered {task_type} task {task_id} for KB {kb_id}")
        else:
            logger.warning(f"Failed to register {task_type} task - duplicate exists")
            
        return success
    
    @staticmethod
    def unregister_task(task_type: str, kb_id: str, unique_key: str = None):
        """Remove task registration when complete"""
        key = f"task:{task_type}:{kb_id}"
        if unique_key:
            key += f":{unique_key}"
        redis_client.delete(key)
        logger.info(f"Unregistered {task_type} task for KB {kb_id}")
    
    @staticmethod
    def check_concurrent_limit(task_type: str) -> bool:
        """
        Check if we've reached the concurrent task limit.
        Returns True if limit reached, False otherwise.
        """
        pattern = f"task:{task_type}:*"
        current_count = len(list(redis_client.scan_iter(match=pattern)))
        max_allowed = TaskProtection.MAX_CONCURRENT_TASKS.get(task_type, 10)
        
        if current_count >= max_allowed:
            logger.warning(
                f"Concurrent task limit reached for {task_type}: "
                f"{current_count}/{max_allowed}"
            )
            return True
        return False
    
    @staticmethod
    def cleanup_stale_tasks(task_type: str = None):
        """Clean up any stale task registrations"""
        pattern = f"task:{task_type or '*'}:*"
        cleaned = 0
        
        for key in redis_client.scan_iter(match=pattern):
            # Check if task has TTL (if not, it's stale)
            ttl = redis_client.ttl(key)
            if ttl == -1:  # No expiration set
                redis_client.delete(key)
                cleaned += 1
                
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} stale task registrations")
        return cleaned


def prevent_duplicate_task(task_type: str, get_unique_key=None):
    """
    Decorator to prevent duplicate task execution.
    
    Args:
        task_type: Type of task (scrape, upload, etc.)
        get_unique_key: Function to extract unique key from args
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract KB ID (assuming it's the first argument after self)
            kb_id = args[1] if len(args) > 1 else kwargs.get('kb_id')
            if not kb_id:
                raise ValueError("KB ID required for task protection")
            
            # Get unique key if provided
            unique_key = None
            if get_unique_key:
                unique_key = get_unique_key(*args, **kwargs)
            
            # Check for duplicates
            if TaskProtection.check_duplicate_task(task_type, kb_id, unique_key):
                logger.warning(f"Skipping duplicate {task_type} task for KB {kb_id}")
                return {"status": "skipped", "reason": "duplicate_task"}
            
            # Check concurrent limit
            if TaskProtection.check_concurrent_limit(task_type):
                logger.warning(f"Skipping {task_type} task due to concurrent limit")
                return {"status": "skipped", "reason": "concurrent_limit"}
            
            # Register task
            task_id = getattr(args[0], 'request', {}).get('id', 'unknown')
            if not TaskProtection.register_task(task_type, kb_id, task_id, unique_key):
                return {"status": "skipped", "reason": "registration_failed"}
            
            try:
                # Execute the actual task
                result = func(*args, **kwargs)
                return result
            finally:
                # Always unregister task when done
                TaskProtection.unregister_task(task_type, kb_id, unique_key)
                
        return wrapper
    return decorator


class TaskHealthMonitor:
    """Monitor task health and detect issues"""
    
    @staticmethod
    def check_worker_health() -> Dict[str, Any]:
        """Check if workers are healthy and not overloaded"""
        from app.worker.celery_app import celery_app
        
        try:
            # Inspect active tasks
            inspect = celery_app.control.inspect()
            stats = inspect.stats()
            active = inspect.active()
            
            if not stats:
                return {
                    "healthy": False,
                    "reason": "No workers available",
                    "workers": 0
                }
            
            # Count workers and active tasks
            worker_count = len(stats)
            active_tasks = sum(len(tasks) for tasks in (active or {}).values())
            
            # Check if overloaded
            if active_tasks > worker_count * 10:
                return {
                    "healthy": False,
                    "reason": "Workers overloaded",
                    "workers": worker_count,
                    "active_tasks": active_tasks
                }
            
            return {
                "healthy": True,
                "workers": worker_count,
                "active_tasks": active_tasks
            }
            
        except Exception as e:
            logger.error(f"Failed to check worker health: {e}")
            return {
                "healthy": False,
                "reason": f"Health check failed: {str(e)}"
            }
    
    @staticmethod
    def auto_cleanup_tasks():
        """Automatically clean up stale tasks and registrations"""
        logger.info("Running automatic task cleanup")
        
        # Clean up stale Redis keys
        TaskProtection.cleanup_stale_tasks()
        
        # TODO: Add database cleanup for old task records
        
        return {"status": "cleanup_complete"} 
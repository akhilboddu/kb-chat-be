from app.worker.celery_app import celery_app
from app.core.embeddings_flexible import HuggingFaceEmbeddings
from app.utils.logging import get_logger
import gc
import os

logger = get_logger(__name__)

@celery_app.task(bind=True)
def cleanup_idle_workers(self):
    """Periodic task to clean up memory when workers are idle"""
    # Check if any tasks are running
    active = celery_app.control.inspect().active() or {}
    
    # Check if there are any active tasks across all workers
    has_active_tasks = False
    for worker_tasks in active.values():
        if worker_tasks:  # Check if list is not empty
            has_active_tasks = True
            break
    
    if not has_active_tasks:
        # No active tasks, clean up
        try:
            # Clean up HuggingFace models from cache
            HuggingFaceEmbeddings.cleanup_models()
            
            # Force garbage collection
            gc.collect()
            
            logger.info("cleanup_completed", worker_id=self.request.hostname)
            return {"status": "cleaned", "worker_id": self.request.hostname}
        except Exception as e:
            logger.error("cleanup_failed", error=str(e), worker_id=self.request.hostname)
            return {"status": "failed", "error": str(e), "worker_id": self.request.hostname}
    
    return {"status": "skipped", "reason": "workers_busy", "worker_id": self.request.hostname}

# Configure celerybeat schedule
from celery.schedules import crontab

# Add to celerybeat schedule
celery_app.conf.beat_schedule = celery_app.conf.beat_schedule or {}
celery_app.conf.beat_schedule.update({
    'cleanup-idle-workers': {
        'task': 'app.tasks.cleanup.cleanup_idle_workers',
        'schedule': 300.0,  # Every 5 minutes
    },
})
import os
from celery import Celery, Task
from kombu import Queue
import psutil
from app.utils.logging import get_logger

celery_app = Celery(
    "kb_tasks",
    broker=os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL")),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1"),
)

# Enhanced configuration with timeouts and memory limits
# Extremely conservative settings to prevent connection exhaustion
celery_app.conf.update(
    task_track_started=True,
    result_expires=3600,
    task_soft_time_limit=300,  # 5 min soft limit
    task_time_limit=600,       # 10 min hard limit
    worker_max_tasks_per_child=20,  # Recycle workers after 20 tasks (reduced from 50)
    worker_max_memory_per_child=256000,  # 256MB limit (reduced from 512MB)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_queues=(
        Queue('scrape', routing_key='scrape'),
        Queue('upload', routing_key='upload'),
    ),
    # Minimal concurrency to prevent connection exhaustion
    worker_concurrency=1,  # Only 1 concurrent task per worker (reduced from 2)
    worker_prefetch_multiplier=1,  # Don't prefetch tasks
    # Connection management
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=5,
    # Task execution settings
    task_always_eager=False,  # Don't execute tasks synchronously
    task_store_eager_result=True,
)

# Error retry strategy
class RetryableTask(Task):
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True  # Exponential backoff
    retry_backoff_max = 600  # Max 10 min between retries
    retry_jitter = True  # Add randomness to prevent thundering herd
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure"""
        logger = get_logger(__name__)
        logger.error(f"Task {self.name} failed: {exc}")
        super().on_failure(exc, task_id, args, kwargs, einfo)
    
    def on_success(self, retval, task_id, args, kwargs):
        """Handle task success"""
        logger = get_logger(__name__)
        logger.info(f"Task {self.name} completed successfully")
        super().on_success(retval, task_id, args, kwargs)

# Memory monitoring task
@celery_app.task(bind=True)
def check_memory(self):
    """Monitor worker memory usage."""
    logger = get_logger("memory_monitor")
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / 1024 / 1024
    
    if memory_mb > 400:  # Warning at 400MB
        logger.warning("high_memory_usage", memory_mb=memory_mb, worker_id=self.request.hostname)
    
    return {"memory_mb": memory_mb, "worker_id": self.request.hostname} 
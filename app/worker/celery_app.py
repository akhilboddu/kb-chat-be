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
celery_app.conf.update(
    task_track_started=True,
    result_expires=3600,
    task_soft_time_limit=300,  # 5 min soft limit
    task_time_limit=600,       # 10 min hard limit
    worker_max_tasks_per_child=50,  # Recycle workers after 50 tasks
    worker_max_memory_per_child=512000,  # 500MB limit
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_queues=(
        Queue('scrape', routing_key='scrape'),
        Queue('upload', routing_key='upload'),
    ),
)

# Error retry strategy
class RetryableTask(Task):
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True  # Exponential backoff
    retry_backoff_max = 600  # Max 10 min between retries
    retry_jitter = True  # Add randomness to prevent thundering herd

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
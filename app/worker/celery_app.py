import os
import threading
from celery import Celery, Task, signals
from kombu import Queue
import psutil
import gc
from app.utils.logging import get_logger

# Set environment variables BEFORE importing any ML libraries
# These settings are CRITICAL for preventing segmentation faults in workers
os.environ.update({
    'TOKENIZERS_PARALLELISM': 'false',  # Prevent tokenizer multiprocessing issues
    'OMP_NUM_THREADS': '1',             # Single-threaded BLAS operations
    'MKL_NUM_THREADS': '1',             # Intel MKL threading
    'NUMEXPR_NUM_THREADS': '1',         # NumExpr threading
    'PYTORCH_CUDA_ALLOC_CONF': 'max_split_size_mb:128',  # CUDA memory management
    'HF_HUB_DISABLE_TELEMETRY': '1',    # Disable HuggingFace telemetry
    'TRANSFORMERS_OFFLINE': '0',        # Allow online model downloading
})

# Queue-specific time limits configuration
def get_time_limits(queue_name: str) -> tuple:
    """
    Get queue-specific time limits from environment variables.
    
    Returns:
        tuple: (soft_time_limit, time_limit) in seconds
    """
    if queue_name == 'upload':
        soft_limit = int(os.getenv('UPLOAD_SOFT_LIMIT', '3600'))  # 60 min default for HF CPU embeddings
        hard_limit = int(os.getenv('UPLOAD_HARD_LIMIT', '4200'))  # 70 min default for HF CPU embeddings
    elif queue_name == 'scrape':
        soft_limit = int(os.getenv('SCRAPE_SOFT_LIMIT', '600'))   # 10 min default
        hard_limit = int(os.getenv('SCRAPE_HARD_LIMIT', '900'))   # 15 min default
    else:
        # Default limits for other queues
        soft_limit = 300  # 5 min
        hard_limit = 600  # 10 min
    
    return soft_limit, hard_limit

celery_app = Celery(
    "kb_tasks",
    broker=os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL")),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1"),
    include=['app.tasks.scrape', 'app.tasks.upload', 'app.tasks.optimize', 'app.tasks.cleanup']
)

# Enhanced configuration with thread-based workers for ML stability
# CRITICAL: Use threads instead of processes to prevent segmentation faults
celery_app.conf.update(
    # Worker pool configuration - CRITICAL for ML models
    worker_pool='threads',  # Use thread-based workers instead of process-based
    worker_concurrency=2,   # Conservative thread count to prevent memory issues
    worker_prefetch_multiplier=1,  # Don't prefetch tasks
    
    # Task execution and timing
    task_track_started=True,
    result_expires=3600,
    task_soft_time_limit=1800,  # 30 min soft limit for upload tasks
    task_time_limit=2400,       # 40 min hard limit for upload tasks
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Worker lifecycle management
    worker_max_tasks_per_child=50,  # Restart workers periodically to prevent memory leaks
    worker_max_memory_per_child=3072000,  # 3GB memory limit per worker (optimized for m5.xlarge)
    worker_disable_rate_limits=True,  # Disable rate limiting for ML workloads
    
    # Queue configuration
    task_queues=(
        Queue('scrape', routing_key='scrape'),
        Queue('upload', routing_key='upload'),
        Queue('optimize', routing_key='optimize'),
    ),
    
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
    
    if memory_mb > 3000:  # Warning at 3GB (optimized for m5.xlarge)
        logger.warning("high_memory_usage", memory_mb=memory_mb, worker_id=self.request.hostname)
    
    return {"memory_mb": memory_mb, "worker_id": self.request.hostname}


# Health check task for embeddings system
@celery_app.task(bind=True)
def embeddings_health_check(self):
    """Verify HuggingFace embeddings are working correctly."""
    logger = get_logger("embeddings_health")
    try:
        # Import here to avoid issues during worker startup
        from app.core.embeddings_flexible import get_embeddings
        
        # Get embeddings instance
        embeddings = get_embeddings()
        
        # Test embedding generation
        test_embedding = embeddings.embed_query("health check test")
        
        # Verify embedding properties
        if not test_embedding or len(test_embedding) == 0:
            return {"status": "unhealthy", "error": "Empty embedding returned"}
        
        # Check dimensions
        expected_dim = embeddings.get_embedding_info().get("dimension", 1024)
        if len(test_embedding) != expected_dim:
            return {
                "status": "unhealthy", 
                "error": f"Dimension mismatch: got {len(test_embedding)}, expected {expected_dim}"
            }
        
        # All checks passed
        return {
            "status": "healthy", 
            "dimensions": len(test_embedding),
            "model": embeddings.get_embedding_info().get("model", "unknown"),
            "provider": embeddings.get_embedding_info().get("provider", "unknown"),
            "worker_id": self.request.hostname
        }
        
    except Exception as e:
        logger.error(f"Embeddings health check failed: {e}")
        return {
            "status": "unhealthy", 
            "error": str(e),
            "worker_id": self.request.hostname
        }


# Memory guard - check memory before running tasks
@signals.task_prerun.connect
def memory_guard(**kwargs):
    """Check memory before running tasks"""
    logger = get_logger("memory_guard")
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / 1024 / 1024
    
    if memory_mb > 3000:  # Warning at 3GB
        logger.warning("high_memory_before_task", memory_mb=memory_mb)
        try:
            # Force cleanup
            from app.core.embeddings_flexible import HuggingFaceEmbeddings
            HuggingFaceEmbeddings.cleanup_models()
            gc.collect()
            
            # Check memory again
            new_memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info("memory_after_cleanup", 
                       before_mb=memory_mb, 
                       after_mb=new_memory_mb,
                       freed_mb=memory_mb - new_memory_mb)
        except Exception as e:
            logger.error("memory_cleanup_failed", error=str(e)) 
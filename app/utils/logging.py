import structlog
from contextvars import ContextVar
from functools import wraps
import uuid

# Context variable for correlation ID
correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

def get_logger(name: str):
    """Get a logger instance with correlation ID context."""
    return structlog.get_logger(name).bind(correlation_id=correlation_id.get())

def task_with_correlation(func):
    """Decorator to add correlation ID and structured logging to tasks."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Set a new correlation ID for this task
        correlation_id.set(str(uuid.uuid4()))
        logger = get_logger(func.__name__)
        logger.info("task_started", args=args)
        try:
            result = func(*args, **kwargs)
            logger.info("task_completed")
            return result
        except Exception as e:
            logger.error("task_failed", error=str(e))
            raise
    return wrapper 
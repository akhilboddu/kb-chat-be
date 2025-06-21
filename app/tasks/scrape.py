from app.worker.celery_app import celery_app, RetryableTask
from app.services.scrape_service import run_scrape_and_populate
from app.utils.logging import task_with_correlation
from app.utils.task_protection import prevent_duplicate_task
import asyncio
from celery.utils.log import get_task_logger

@celery_app.task(bind=True, base=RetryableTask, queue="scrape", 
                 soft_time_limit=600, time_limit=660)  # 10 min soft, 11 min hard
@task_with_correlation
@prevent_duplicate_task("scrape", lambda *args, **kwargs: args[2])  # Use URL as unique key
def run_scrape_task(self, kb_id, url, max_pages=None):
    """
    Celery task to run the scrape and populate operation.
    This wraps the async function to run in Celery's sync context.
    
    Protected against:
    - Duplicate scraping of same URL for same KB
    - Running too many concurrent scrape tasks
    - Tasks running longer than 10 minutes
    """
    task_logger = get_task_logger(__name__)
    task_logger.info(f"[SCRAPE TASK] Starting task id={self.request.id} kb_id={kb_id} url={url} max_pages={max_pages}")
    # Run the async function in a new event loop
    asyncio.run(run_scrape_and_populate(kb_id, url, max_pages)) 
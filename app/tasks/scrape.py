from app.worker.celery_app import celery_app, RetryableTask
from app.services.scrape_service import run_scrape_and_populate
from app.utils.logging import task_with_correlation
import asyncio

@celery_app.task(bind=True, base=RetryableTask, queue="scrape")
@task_with_correlation
def run_scrape_task(self, kb_id, url, max_pages=None):
    """
    Celery task to run the scrape and populate operation.
    This wraps the async function to run in Celery's sync context.
    """
    # Run the async function in a new event loop
    asyncio.run(run_scrape_and_populate(kb_id, url, max_pages)) 
from app.worker.celery_app import celery_app, RetryableTask
from app.services.file_upload_service import process_files_background
from app.utils.logging import task_with_correlation
import asyncio

@celery_app.task(bind=True, base=RetryableTask, queue="upload")
@task_with_correlation
def run_upload_task(self, kb_id, file_data_list, initial_failed_files=0):
    """
    Celery task to run the file upload and processing operation.
    This wraps the async function to run in Celery's sync context.
    """
    # Run the async function in a new event loop
    asyncio.run(process_files_background(kb_id, file_data_list, initial_failed_files)) 
from app.worker.celery_app import celery_app, RetryableTask
from app.services.file_upload_service import process_files_background
from app.utils.logging import task_with_correlation
from app.utils.task_protection import prevent_duplicate_task
import asyncio
import hashlib
import json

def get_files_hash(*args, **kwargs):
    """Generate a unique hash for the file list to prevent duplicate uploads"""
    file_data_list = args[2] if len(args) > 2 else kwargs.get('file_data_list', [])
    # Create a hash of filenames and sizes
    file_info = [(f.get('filename', ''), f.get('size', 0)) for f in file_data_list]
    return hashlib.md5(json.dumps(sorted(file_info)).encode()).hexdigest()[:8]

@celery_app.task(bind=True, base=RetryableTask, queue="upload",
                 soft_time_limit=300, time_limit=360)  # 5 min soft, 6 min hard
@task_with_correlation
@prevent_duplicate_task("upload", get_files_hash)
def run_upload_task(self, kb_id, file_data_list, initial_failed_files=0):
    """
    Celery task to run the file upload and processing operation.
    This wraps the async function to run in Celery's sync context.
    
    Protected against:
    - Duplicate upload of same files to same KB
    - Running too many concurrent upload tasks
    - Tasks running longer than 5 minutes
    """
    # Run the async function in a new event loop
    asyncio.run(process_files_background(kb_id, file_data_list, initial_failed_files)) 
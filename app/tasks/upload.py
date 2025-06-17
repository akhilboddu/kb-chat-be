from app.worker.celery_app import celery_app, RetryableTask, get_time_limits
from app.services.file_upload_service import process_files_background
from app.utils.logging import task_with_correlation
from app.utils.task_protection import prevent_duplicate_task
from celery.exceptions import SoftTimeLimitExceeded
from app.core import supabase_metadata_manager as db_manager
import hashlib
import json

def get_files_hash(*args, **kwargs):
    """Generate a unique hash for the file list to prevent duplicate uploads"""
    file_data_list = args[2] if len(args) > 2 else kwargs.get('file_data_list', [])
    # Create a hash of filenames, sizes, and timestamps to allow retries
    import time
    file_info = [(f.get('filename', ''), f.get('size', 0), int(time.time() // 60)) for f in file_data_list]  # Group by minute
    return hashlib.md5(json.dumps(sorted(file_info)).encode()).hexdigest()[:8]

# Get upload-specific time limits
upload_soft_limit, upload_hard_limit = get_time_limits('upload')

@celery_app.task(bind=True, base=RetryableTask, queue="upload",
                 soft_time_limit=upload_soft_limit, time_limit=upload_hard_limit)
@task_with_correlation
@prevent_duplicate_task("upload", get_files_hash)
def run_upload_task(self, kb_id, file_data_list, initial_failed_files=0):
    """
    Celery task to run the file upload and processing operation.
    This wraps the async function to run in Celery's sync context.
    
    Protected against:
    - Duplicate upload of same files to same KB
    - Running too many concurrent upload tasks
    - Tasks running longer than configured time limits
    """
    try:
        # Import asyncio and handle event loop properly
        import asyncio
        
        # Check if there's already a running event loop
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context - this shouldn't happen in Celery, but handle it
            print("Warning: Already in async context, this may cause issues")
            # Create a new thread to run the async function
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, process_files_background(kb_id, file_data_list, initial_failed_files))
                future.result()
        except RuntimeError:
            # No event loop running, safe to create one
            asyncio.run(process_files_background(kb_id, file_data_list, initial_failed_files))
    except SoftTimeLimitExceeded:
        # Update status to failed before the task is killed
        db_manager.update_file_upload_status(
            kb_id,
            {
                "status": "failed",
                "message": "Upload exceeded time limit and was terminated",
                "progress": {
                    "stage": "failed",
                    "details": "Task exceeded time limit",
                    "percent": 0
                }
            }
        )
        raise  # Re-raise to let Celery handle the exception 
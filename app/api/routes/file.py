import os
from fastapi import APIRouter, HTTPException, UploadFile, File, status, BackgroundTasks, Depends
from typing import List, Dict, Any
import io
import asyncio

from app.core import supabase_metadata_manager as db_manager, kb_manager, file_parser, supabase_client
from app.models.base import StatusResponse
from app.models.file import ListFilesResponse, UploadedFileInfo, FileUploadStatusResponse
from app.services.file_upload_service import process_files_background
from app.tasks.upload import run_upload_task
from app.utils.cookie_auth import require_cookie_auth

router = APIRouter(tags=["files"])


@router.post("/agents/{kb_id}/upload", response_model=StatusResponse, dependencies=[Depends(require_cookie_auth)])
async def upload_to_kb(
    kb_id: str, 
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None
):
    """
    Accepts multiple file uploads and processes them in the background.
    Returns immediately with a processing status.
    """
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided for upload.")

    # Read file contents immediately to avoid issues with closed file handles in background tasks
    file_data_list = []
    failed_files = 0
    
    for file in files:
        try:
            if not file.filename:
                failed_files += 1
                continue
                
            # Read the file content into memory
            content = await file.read()
            file_data = {
                "filename": file.filename,
                "content": content,
                "content_type": file.content_type,
                "size": len(content)
            }
            file_data_list.append(file_data)
        except Exception as e:
            print(f"Error reading file {file.filename}: {e}")
            failed_files += 1
            continue

    if not file_data_list:
        raise HTTPException(status_code=400, detail="All files failed to read.")

    # Initialize the status
    initial_status = {
        "status": "processing",
        "total_files": len(file_data_list),
        "processed_files": 0,
        "failed_files": failed_files,
        "message": f"Upload initiated for {len(file_data_list)} file(s)" + (f" ({failed_files} failed to read)" if failed_files > 0 else ""),
        "progress": {
            "stage": "initialized",
            "details": "🪄 Starting upload",
            "percent": 0
        }
    }
    
    print(f"Initializing upload status for KB {kb_id} with {len(file_data_list)} files")
    
    # Check if we should use Celery
    use_celery = os.getenv("USE_CELERY", "true").lower() == "true"
    
    if use_celery:
        # Queue task with Celery
        result = run_upload_task.apply_async(
            args=[kb_id, file_data_list, failed_files]
        )
        # Add Celery task ID to status
        initial_status["celery_id"] = result.id
        print(f"Queued upload task with Celery ID: {result.id}")
    
    # Update initial status and ensure it succeeds
    status_updated = db_manager.update_file_upload_status(kb_id, initial_status)
    if not status_updated:
        print(f"Failed to initialize upload status for KB {kb_id}")
        raise HTTPException(
            status_code=500, 
            detail="Failed to initialize file upload status"
        )
    
    print(f"Successfully initialized upload status for KB {kb_id}")
    
    # If not using Celery, use asyncio as fallback
    if not use_celery:
        # Run the background processing in a separate thread to avoid blocking the event loop
        async def _run_in_thread():
            await asyncio.to_thread(
                lambda: asyncio.run(
                    process_files_background(
                        kb_id=kb_id,
                        file_data_list=file_data_list,
                        initial_failed_files=failed_files
                    )
                )
            )

        # Fire and forget using asyncio (non-blocking)
        asyncio.create_task(_run_in_thread())
        print("Using asyncio for file processing (Celery disabled)")
    
    return StatusResponse(
        status="processing",
        message=f"File upload initiated in background for {len(file_data_list)} file(s)"
    )


@router.get("/agents/{kb_id}/upload-status", response_model=FileUploadStatusResponse, dependencies=[Depends(require_cookie_auth)])
async def get_upload_status(kb_id: str):
    """
    Get the current status of a file upload operation for a specific KB.
    """
    print(f"Getting upload status for KB: {kb_id}")
    try:
        status = db_manager.get_file_upload_status(kb_id)
        if not status:
            print(f"No upload status found for KB: {kb_id}")
            # Return a "not_found" status instead of 404 to match the scrape status behavior
            return FileUploadStatusResponse(
                kb_id=kb_id,
                status="not_found",
                message="No file upload operation found",
                total_files=0,
                processed_files=0,
                failed_files=0
            )
        
        print(f"Found upload status for KB {kb_id}: {status.get('status', 'unknown')} - {status.get('message', '')}")
        
        # Ensure all required fields are present
        return FileUploadStatusResponse(
            kb_id=kb_id,
            status=status.get("status", "unknown"),
            message=status.get("message", ""),
            total_files=status.get("total_files", 0),
            processed_files=status.get("processed_files", 0),
            failed_files=status.get("failed_files", 0),
            progress=status.get("progress", {})
        )
    except Exception as e:
        print(f"Error retrieving upload status for KB {kb_id}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve upload status: {str(e)}"
        )


@router.get("/agents/{kb_id}/files", response_model=ListFilesResponse, dependencies=[Depends(require_cookie_auth)])
async def list_uploaded_files_endpoint(kb_id: str):
    """
    Lists metadata for all files uploaded to a specific knowledge base.
    """
    print(f"Received request to list uploaded files for KB: {kb_id}")
    try:
        # Verify KB exists (optional but good practice)
        # _ = kb_manager.create_or_get_kb(kb_id) # This might raise NotFoundError if KB doesn't exist

        file_info_list = db_manager.get_uploaded_files(kb_id)

        # Map the list of dicts to a list of UploadedFileInfo models
        files_response = [UploadedFileInfo(**info) for info in file_info_list]

        return ListFilesResponse(kb_id=kb_id, files=files_response)
    # except NotFoundError:
    #     raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found.")
    except Exception as e:
        print(f"Error listing uploaded files for KB {kb_id}: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to list uploaded files: {str(e)}"
        )


@router.post("/bots/{bot_id}/upload", response_model=StatusResponse, deprecated=True, dependencies=[Depends(require_cookie_auth)])
async def bot_upload_endpoint(
    bot_id: str, 
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None
):
    """
    [DEPRECATED] Upload files to a bot's knowledge base.
    This endpoint is deprecated in favor of /agents/{kb_id}/upload.
    It will be removed in a future version.
    """
    print(f"[DEPRECATED] Received upload request for bot_id: {bot_id}")
    print(f"Files: {files}")
    
    # Get the kb_id from bot_id
    response = (
        supabase_client.supabase.table("bots").select("*").eq("id", bot_id).execute()
    )
    
    if not response.data:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    
    kb_id = response.data[0]["kb_id"]
    
    # Call the new upload endpoint
    return await upload_to_kb(kb_id, files, background_tasks)


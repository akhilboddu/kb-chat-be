import os
from fastapi import APIRouter, HTTPException, UploadFile, File, status
from typing import List

import db_manager
from kb_manager import kb_manager
from file_parser import parse_file, get_file_extension
from app.models.base import StatusResponse
from app.models.file import ListFilesResponse, UploadedFileInfo
from supabase_client import supabase

router = APIRouter(tags=["files"])

@router.post("/agents/{kb_id}/upload", response_model=StatusResponse)
async def upload_to_kb(kb_id: str, files: List[UploadFile] = File(...)):
    """
    Accepts multiple file uploads, parses their content, stores file metadata,
    and adds the extracted text to the specified knowledge base.
    """
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided for upload.")
    
    processed_files = 0
    failed_files = 0
    no_content_files = 0
    
    for file in files:
        print(f"Processing file for kb_id: {kb_id}. Filename: {file.filename}, Content-Type: {file.content_type}")

        if not file.filename:
            print(f"Skipping file with no filename in request")
            failed_files += 1
            continue

        # --- Store File Metadata ---
        # Get file size (requires reading the file or seeking)
        file.file.seek(0, os.SEEK_END)
        file_size = file.file.tell()
        file.file.seek(0) # Reset file pointer for parsing
        print(f"Storing file record for '{file.filename}' ({file_size} bytes)... ")
        record_success = db_manager.add_uploaded_file_record(
            kb_id=kb_id,
            filename=file.filename,
            file_size=file_size,
            content_type=file.content_type
        )
        if not record_success:
            print(f"Error: Failed to store file metadata record for '{file.filename}' in KB {kb_id}. Skipping this file.")
            failed_files += 1
            continue

        # --- Parse File Content ---
        raw_extracted_text: str = None
        try:
            raw_extracted_text = await parse_file(file)
        except Exception as e:
            print(f"Error during file parsing for {file.filename}: {e}")
            import traceback
            traceback.print_exc()
            failed_files += 1
            continue
        
        if raw_extracted_text is None:
            print(f"Unsupported file type or failed to parse file: {file.filename}")
            failed_files += 1
            continue
            
        if not raw_extracted_text.strip():
            print(f"File {file.filename} parsed successfully but contained no text content.")
            no_content_files += 1
            continue
        
        # PDF parsing now happens directly into Markdown via pymupdf4llm in file_parser.py
        text_to_add = raw_extracted_text 
        file_extension = get_file_extension(file.filename)
        
        # --- Add to Knowledge Base --- 
        print(f"Adding parsed text from {file.filename} to KB {kb_id}...") # Simplified log
        try:
            success = kb_manager.add_to_kb(kb_id, text_to_add)
            if success:
                # Simplified message, as structuring is now part of parsing for PDFs
                parsed_as = "Markdown" if file_extension == '.pdf' else "text"
                print(f"Successfully added content (parsed as {parsed_as}) from {file.filename} to KB {kb_id}.")
                processed_files += 1
            else:
                print(f"Failed to add content from {file.filename} to KB {kb_id} (add_to_kb returned False).")
                failed_files += 1
        except Exception as e:
            print(f"Error adding parsed content from {file.filename} to KB {kb_id}: {e}")
            failed_files += 1

    # Generate a summary message based on processing results
    message = f"Processed {processed_files} file(s) successfully"
    if no_content_files > 0:
        message += f", {no_content_files} file(s) had no text content"
    if failed_files > 0:
        message += f", {failed_files} file(s) failed to process"
    
    if processed_files == 0 and (failed_files > 0 or no_content_files > 0):
        # If we processed nothing but had failures, return a 207 (Multi-Status)
        # or could use 422 Unprocessable Entity or 500 Internal Server Error
        if failed_files > 0:
            raise HTTPException(status_code=422, detail=message)
        else:
            # All files were processed but had no content
            return StatusResponse(status="warning", message=message)
    
    return StatusResponse(status="success", message=message)


@router.get("/agents/{kb_id}/files", response_model=ListFilesResponse)
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
        raise HTTPException(status_code=500, detail=f"Failed to list uploaded files: {str(e)}")


@router.post("/bots/{bot_id}/upload", response_model=StatusResponse)
async def bot_upload_endpoint(bot_id: str, files: List[UploadFile] = File(...)):
    """
    Upload files to a bot's knowledge base.
    """
    print(f"Received upload request for bot_id: {bot_id}")
    print(f"Files: {files}")
    # also add to knowledge_sources table under supabase
    for file in files:
        fileContent = ""
        fileExtension = file.filename.split(".")[-1]

        # Read file size
        file.file.seek(0, os.SEEK_END)
        file_size = file.file.tell()
        file.file.seek(0)  # Reset file pointer
        
        # Format with Python's f-string formatting for floating point (:.1f for 1 decimal place)
        fileContent = f"File: {file.filename} ({file.content_type or f'{fileExtension} file'}) - Size: {file_size / 1024:.1f} KB"

        sourceData = {
            "bot_id": bot_id,
            "source_type": "file",
            "content": fileContent
        }
        response = supabase.table("knowledge_sources").insert(sourceData).execute()
        print(f"Knowledge source added: {response}")

    response = supabase.table("bots").select("*").eq("id", bot_id).execute()
    print(f"Bot response: {response}")

    kb_id = response.data[0]["kb_id"]

    # now use all logic from /agents/{kb_id}/upload endpoint
    return await upload_to_kb(kb_id, files) 
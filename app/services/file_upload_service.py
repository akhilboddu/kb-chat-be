import os
import tempfile
import shutil
import logging
from typing import List, Dict, Any
from fastapi import UploadFile
import io

from app.core import supabase_metadata_manager as db_manager, kb_manager, file_parser
from app.core.supabase_client import supabase

logger = logging.getLogger(__name__)


async def process_files_background(kb_id: str, file_data_list: List[Dict[str, Any]], initial_failed_files: int = 0):
    """Processes file uploads in the background, updating status as it progresses."""
    logger.info(f"[Background Task] Starting file upload processing for KB '{kb_id}' with {len(file_data_list)} files")
    
    total_files = len(file_data_list)
    processed_files = 0
    failed_files = initial_failed_files
    no_content_files = 0
    current_status = "processing"
    
    # Update initial status to reflect any files that failed to read
    db_manager.update_file_upload_status(
        kb_id,
        {
            "status": current_status,
            "total_files": total_files + initial_failed_files,
            "processed_files": 0,
            "failed_files": initial_failed_files,
            "message": f"Processing {total_files} files" + (f" ({initial_failed_files} failed)" if initial_failed_files > 0 else ""),
            "progress": {
                "stage": "initialized",
                "details": "Starting upload",
                "percent": 0
            }
        }
    )
    
    try:
        # Process each file
        for idx, file_data in enumerate(file_data_list):
            filename = file_data["filename"]
            content = file_data["content"]
            content_type = file_data["content_type"]
            file_size = file_data["size"]
            
            # Calculate base progress for this file
            file_base_percent = int((idx / total_files) * 100) if total_files > 0 else 0
            file_increment = int(100 / total_files) if total_files > 0 else 100
                
            # Stage 1: Starting file processing (0% of file progress)
            db_manager.update_file_upload_status(
                kb_id,
                {
                    "status": current_status,
                    "total_files": total_files + initial_failed_files,
                    "processed_files": processed_files,
                    "failed_files": failed_files,
                    "message": f"File {idx + 1}/{total_files}: {filename}",
                    "progress": {
                        "stage": "processing_file",
                        "details": f"📥 {filename}",
                        "percent": file_base_percent
                    }
                }
            )
            
            logger.info(f"Processing file {idx + 1}/{total_files} for kb_id: {kb_id}. Filename: {filename}")
            
            # Stage 2: Storing metadata (10% of file progress)
            record_success = db_manager.add_uploaded_file_record(
                kb_id=kb_id,
                filename=filename,
                file_size=file_size,
                content_type=content_type,
            )
            
            if not record_success:
                logger.error(f"Failed to store file metadata for '{filename}'")
                failed_files += 1
                continue
            
            # Update progress after metadata storage
            db_manager.update_file_upload_status(
                kb_id,
                {
                    "status": current_status,
                    "total_files": total_files + initial_failed_files,
                    "processed_files": processed_files,
                    "failed_files": failed_files,
                    "message": f"Parsing {idx + 1}/{total_files}: {filename}",
                    "progress": {
                        "stage": "parsing_file",
                        "details": f"🔍 {filename}",
                        "percent": file_base_percent + int(file_increment * 0.1)
                    }
                }
            )
            
            # Stage 3: Parse file content (parsing start – 30% of file progress)
            try:
                logger.info(f"Starting to parse file: {filename}")
                
                # Create an UploadFile object from the content in memory
                temp_upload_file = UploadFile(
                    filename=filename,
                    file=io.BytesIO(content)
                )
                logger.info(f"Created UploadFile object for parsing: {filename}")
                
                # Update progress at parsing start (give UI an early update)
                db_manager.update_file_upload_status(
                    kb_id,
                    {
                        "status": current_status,
                        "total_files": total_files + initial_failed_files,
                        "processed_files": processed_files,
                        "failed_files": failed_files,
                        "message": f"Parsing file {idx + 1} of {total_files}: {filename}",
                        "progress": {
                            "stage": "parsing_file",
                            "details": f"🔍 Extracting text from: {filename}",
                            "percent": file_base_percent + int(file_increment * 0.3)
                        }
                    }
                )
                
                raw_extracted_text = await file_parser.parse_file(temp_upload_file)
                
                # Update progress at parsing complete (50% of file progress)
                db_manager.update_file_upload_status(
                    kb_id,
                    {
                        "status": current_status,
                        "total_files": total_files + initial_failed_files,
                        "processed_files": processed_files,
                        "failed_files": failed_files,
                        "message": f"Parsed {filename}",
                        "progress": {
                            "stage": "parsing_complete",
                            "details": f"📄 {filename}",
                            "percent": file_base_percent + int(file_increment * 0.5)
                        }
                    }
                )
                
            except Exception as e:
                logger.error(f"Error during file parsing for {filename}: {e}")
                import traceback
                traceback.print_exc()
                failed_files += 1
                continue
                
            if raw_extracted_text is None:
                logger.warning(f"Unsupported file type or failed to parse: {filename}")
                failed_files += 1
                continue
                
            if not raw_extracted_text.strip():
                logger.warning(f"File {filename} parsed but contained no text content")
                no_content_files += 1
                continue
            
            # Update progress before embedding (70% of file progress)
            db_manager.update_file_upload_status(
                kb_id,
                {
                    "status": current_status,
                    "total_files": total_files + initial_failed_files,
                    "processed_files": processed_files,
                    "failed_files": failed_files,
                    "message": f"Processing {filename}",
                    "progress": {
                        "stage": "processing",
                        "details": f"🧠 Processing {filename}",
                        "percent": file_base_percent + int(file_increment * 0.7)
                    }
                }
            )

            # Stage 4: Add to knowledge base with batch processing
            logger.info(f"Adding parsed text from {filename} to KB {kb_id} - text length: {len(raw_extracted_text)}")
            
            try:
                # Define progress callback for KB operations
                def kb_progress_callback(kb_percent: int, kb_message: str):
                    # Map KB progress (0-100) to file progress (70-100%)
                    file_progress = file_base_percent + int(file_increment * (0.7 + 0.3 * kb_percent / 100))
                    
                    # Ensure we reach 100% for the last file when KB processing is complete
                    if kb_percent >= 100 and idx == len(file_data_list) - 1:
                        file_progress = 100
                    
                    # Log progress calculation for debugging
                    logger.info(f"KB Progress: {kb_percent}% -> File Progress: {file_progress}% (base: {file_base_percent}, increment: {file_increment})")
                    
                    db_manager.update_file_upload_status(
                        kb_id,
                        {
                            "status": current_status,
                            "total_files": total_files + initial_failed_files,
                            "processed_files": processed_files,
                            "failed_files": failed_files,
                            "message": f"{filename}: {kb_message}",
                            "progress": {
                                "stage": "kb_processing",
                                "details": f"📊 {filename}: {kb_message}",
                                "percent": file_progress
                            }
                        }
                    )

                logger.info(f"Calling kb_manager.add_to_kb for {filename}")
                
                # Retry logic for knowledge base addition
                max_retries = 3
                success = False
                last_error = None
                
                for attempt in range(max_retries):
                    try:
                        # Use the add_to_kb method which now internally uses batch processing
                        success = kb_manager.add_to_kb(
                            kb_id,
                            raw_extracted_text,
                            knowledge_source="file",
                            source_name=filename,
                            metadata={"file_size": file_size, "content_type": content_type},
                            progress_callback=kb_progress_callback
                        )
                        
                        if success:
                            logger.info(f"kb_manager.add_to_kb succeeded on attempt {attempt + 1} for {filename}")
                            break
                        else:
                            last_error = f"add_to_kb returned False"
                            logger.warning(f"kb_manager.add_to_kb returned False on attempt {attempt + 1} for {filename}")
                            
                    except Exception as e:
                        last_error = str(e)
                        logger.error(f"kb_manager.add_to_kb failed on attempt {attempt + 1} for {filename}: {e}")
                        
                        if attempt < max_retries - 1:
                            import time
                            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                            logger.info(f"Retrying in {wait_time} seconds...")
                            time.sleep(wait_time)
                        else:
                            logger.error(f"All {max_retries} attempts failed for {filename}. Last error: {last_error}")
                
                if success:
                    file_extension = file_parser.get_file_extension(filename)
                    parsed_as = "Markdown" if file_extension == ".pdf" else "text"
                    logger.info(f"Successfully added content (parsed as {parsed_as}) from {filename}")
                    processed_files += 1
                    
                    # Final per-file completion update - ensure we reach 100% for the last file
                    final_percent = file_base_percent + file_increment
                    if idx == len(file_data_list) - 1:
                        # This is the last file, ensure we're at 100%
                        final_percent = 100
                    
                    db_manager.update_file_upload_status(
                        kb_id,
                        {
                            "status": current_status,
                            "total_files": total_files + initial_failed_files,
                            "processed_files": processed_files,
                            "failed_files": failed_files,
                            "message": f"Completed {idx + 1}/{total_files}",
                            "progress": {
                                "stage": "file_complete",
                                "details": f"✅ {filename}",
                                "percent": final_percent
                            }
                        }
                    )
                    
                    # Update knowledge_sources table (similar to scrape service)
                    try:
                        bot_response = supabase.table("bots").select("id").eq("kb_id", kb_id).execute()
                        if bot_response.data and len(bot_response.data) > 0:
                            bot_id = bot_response.data[0]["id"]
                            file_size_kb = file_size / 1024
                            knowledge_source_data = {
                                "bot_id": bot_id,
                                "source_type": "file",
                                "content": f"File: {filename} ({content_type or 'Unknown type'}) - Size: {file_size_kb:.1f} KB"
                            }
                            supabase.table("knowledge_sources").insert(knowledge_source_data).execute()
                    except Exception as e:
                        logger.error(f"Failed to update knowledge_sources table: {str(e)}")
                    
                else:
                    logger.error(f"Failed to add content from {filename} to KB after {max_retries} attempts. Last error: {last_error}")
                    failed_files += 1
                    
                    # Update status to show specific failure
                    db_manager.update_file_upload_status(
                        kb_id,
                        {
                            "status": current_status,
                            "total_files": total_files + initial_failed_files,
                            "processed_files": processed_files,
                            "failed_files": failed_files,
                            "message": f"Failed to process {filename}: {last_error}",
                            "progress": {
                                "stage": "file_failed",
                                "details": f"❌ {filename} - {last_error}",
                                "percent": file_base_percent + file_increment
                            }
                        }
                    )
                    
            except Exception as e:
                logger.error(f"Unexpected error processing {filename}: {e}")
                import traceback
                traceback.print_exc()
                failed_files += 1
                
                # Update status to show unexpected failure
                db_manager.update_file_upload_status(
                    kb_id,
                    {
                        "status": current_status,
                        "total_files": total_files + initial_failed_files,
                        "processed_files": processed_files,
                        "failed_files": failed_files,
                        "message": f"Unexpected error processing {filename}: {str(e)}",
                        "progress": {
                            "stage": "file_error",
                            "details": f"⚠️ {filename} - Unexpected error",
                            "percent": file_base_percent + file_increment
                        }
                    }
                )
                
        # Final status update
        final_status = "completed"
        if failed_files > 0 and processed_files > 0:
            final_status = "completed_with_errors"
        elif failed_files > 0 and processed_files == 0:
            final_status = "failed"
            
        # Generate final message
        if processed_files == 1:
            message = "1 file processed"
        else:
            message = f"{processed_files} files processed"
            
        if no_content_files > 0:
            message += f", {no_content_files} empty"
        if failed_files > 0:
            message += f", {failed_files} failed"
            
        db_manager.update_file_upload_status(
            kb_id,
            {
                "status": final_status,
                "total_files": total_files + initial_failed_files,
                "processed_files": processed_files,
                "failed_files": failed_files,
                "message": message,
                "progress": {
                    "stage": "completed",
                    "details": "✅ " + message,
                    "percent": 100
                }
            }
        )
        
        logger.info(f"[Background Task] Completed file upload processing for KB '{kb_id}': {message}")
        
    except Exception as e:
        logger.exception(f"[Background Task] Unhandled exception during file processing for KB '{kb_id}': {e}")
        db_manager.update_file_upload_status(
            kb_id,
            {
                "status": "failed",
                "total_files": total_files + initial_failed_files,
                "processed_files": processed_files,
                "failed_files": failed_files,
                "message": f"Processing failed: {str(e)}",
                "progress": {
                    "stage": "failed",
                    "details": f"Unhandled exception: {str(e)}",
                    "percent": 0
                }
            }
        ) 
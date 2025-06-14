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
                    "message": f"Embedding {filename}",
                    "progress": {
                        "stage": "embedding",
                        "details": f"🧠 {filename}",
                        "percent": file_base_percent + int(file_increment * 0.7)
                    }
                }
            )

            # Additional progress ping (90% of file progress) before heavy embedding work
            db_manager.update_file_upload_status(
                kb_id,
                {
                    "status": current_status,
                    "total_files": total_files + initial_failed_files,
                    "processed_files": processed_files,
                    "failed_files": failed_files,
                    "message": f"Finalizing {filename}",
                    "progress": {
                        "stage": "embedding_finalising",
                        "details": f"🔗 {filename}",
                        "percent": file_base_percent + int(file_increment * 0.9)
                    }
                }
            )

            # Stage 4: Add to knowledge base (80% of file progress)
            logger.info(f"Adding parsed text from {filename} to KB {kb_id} - text length: {len(raw_extracted_text)}")
            try:
                logger.info(f"Calling kb_manager.add_to_kb for {filename}")
                success = kb_manager.add_to_kb(
                    kb_id,
                    raw_extracted_text,
                    knowledge_source="file",
                    source_name=filename,
                    metadata={"file_size": file_size, "content_type": content_type}
                )
                logger.info(f"kb_manager.add_to_kb returned: {success} for {filename}")
                
                if success:
                    file_extension = file_parser.get_file_extension(filename)
                    parsed_as = "Markdown" if file_extension == ".pdf" else "text"
                    logger.info(f"Successfully added content (parsed as {parsed_as}) from {filename}")
                    processed_files += 1
                    
                    # Final per-file completion update (100% of file progress)
                    db_manager.update_file_upload_status(
                        kb_id,
                        {
                            "status": current_status,
                            "total_files": total_files + initial_failed_files,
                            "processed_files": processed_files,
                            "failed_files": failed_files,
                                                    "message": f"Done {idx + 1}/{total_files}",
                        "progress": {
                            "stage": "file_complete",
                            "details": f"✅ {filename}",
                            "percent": file_base_percent + file_increment
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
                    logger.error(f"Failed to add content from {filename} to KB")
                    failed_files += 1
                    
            except Exception as e:
                logger.error(f"Error adding content from {filename} to KB: {e}")
                failed_files += 1
                
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
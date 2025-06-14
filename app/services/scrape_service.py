import asyncio
import logging
from typing import Optional

from app.core import config, supabase_metadata_manager as db_manager, kb_manager, scraper, data_processor
from app.core.supabase_client import supabase  # Add this import

logger = logging.getLogger(__name__)


async def run_scrape_and_populate(kb_id: str, url: str, max_pages: Optional[int]):
    """Runs the scraping and KB population process in the background."""
    logger.info(
        f"[Background Task] Starting scrape for KB '{kb_id}' from URL: {url} (max_pages: {max_pages or 'default'})"
    )
    current_status = "processing"  # Keep track of the current status

    # Initialize scraping status
    total_pages = max_pages if max_pages else config.get("MAX_INTERNAL_PAGES", 15)
    db_manager.update_scrape_status(
        kb_id,
        {
            "status": current_status,
            "submitted_url": url,
            "pages_scraped": 0,
            "total_pages": total_pages,
            "progress": {
                "stage": "starting", 
                "details": "🌐 Starting web scraping process",
                "percent": 5  # Starting at 5%
            },
        },
    )

    try:
        # 1. Run the scraper
        logger.info(f"[Background Task] Starting scrape for {url}")
        
        # Update progress for scraping start
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,
                "submitted_url": url,
                "pages_scraped": 0,
                "total_pages": total_pages,
                "progress": {
                    "stage": "scraping_pages", 
                    "details": "🔍 Analyzing web pages for content",
                    "percent": 15
                },
            },
        )
        
        # Enhanced progress callback for real-time updates including page counts
        def progress_callback(percent: int, details: str, pages_found: int = 0):
            """Callback to update progress during scraping with real-time page counts"""
            try:
                # Map scraper progress (15-50%) to our overall progress (15-35%)
                adjusted_percent = 15 + ((percent - 15) * 20 / 75)  # Scale 15-90% to 15-35%
                adjusted_percent = max(15, min(35, adjusted_percent))  # Clamp to range
                
                # Update with real-time page count
                db_manager.update_scrape_status(
                    kb_id,
                    {
                        "status": current_status,
                        "submitted_url": url,
                        "pages_scraped": pages_found,  # Real-time page count
                        "total_pages": total_pages,
                        "progress": {
                            "stage": "scraping_pages",
                            "details": details,
                            "percent": int(adjusted_percent)
                        },
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to update progress: {e}")
        
        scrape_result = await scraper.scrape_website(
            url, max_pages=max_pages, progress_callback=progress_callback
        )

        if not scrape_result or "error" in scrape_result:
            error_detail = (
                scrape_result.get("error", "Unknown scraping error")
                if scrape_result
                else "Empty scrape result"
            )
            logger.error(
                f"[Background Task] Scrape failed for KB '{kb_id}', URL '{url}'. Error: {error_detail}"
            )
            current_status = "failed"
            # Update status to failed
            db_manager.update_scrape_status(
                kb_id,
                {
                    "status": current_status,
                    "submitted_url": url,
                    "error": error_detail,
                    "progress": {
                        "stage": "failed",
                        "details": f"Scraping failed: {error_detail}",
                        "percent": 0
                    },
                },
            )
            return  # Stop processing

        # Update pages scraped from metadata (merge with next status update if possible or ensure fields are present)
        pages_scraped_count = 0
        if "scrape_metadata" in scrape_result:
            pages_scraped_count = scrape_result["scrape_metadata"].get(
                "pages_scraped", 0
            )
            # Update status including pages scraped
            db_manager.update_scrape_status(
                kb_id,
                {
                    "status": current_status,  # Still 'processing'
                    "submitted_url": url,
                    "pages_scraped": pages_scraped_count,
                    "progress": {
                        "stage": "scraping_complete",
                        "details": f"✅ Collected {pages_scraped_count} pages successfully",
                        "percent": 35
                    },
                },
            )

        # 2. Extract the business profile
        logger.info(f"[Background Task] Extracting business profile from scraped content")
        
        # Update progress for profile extraction
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,
                "submitted_url": url,
                "pages_scraped": pages_scraped_count,
                "progress": {
                    "stage": "extracting_profile",
                    "details": "📊 Extracting key information from content",
                    "percent": 50
                },
            },
        )
        
        business_profile = scrape_result.get("business_profile")
        if not business_profile or "error" in business_profile:
            error_detail = (
                business_profile.get("error", "Unknown profile compilation error")
                if business_profile
                else "Missing business profile"
            )
            logger.error(
                f"[Background Task] Profile compilation failed for KB '{kb_id}', URL '{url}'. Error: {error_detail}"
            )
            current_status = "failed"
            db_manager.update_scrape_status(
                kb_id,
                {
                    "status": current_status,
                    "submitted_url": url,
                    "error": error_detail,
                    "progress": {
                        "stage": "failed",
                        "details": f"Profile compilation failed: {error_detail}",
                        "percent": 0
                    },
                },
            )
            return  # Stop processing

        logger.info(
            f"[Background Task] Scrape successful for KB '{kb_id}', URL '{url}'. Profile keys: {list(business_profile.keys())}"
        )

        # Update status before processing text
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,  # Still 'processing'
                "submitted_url": url,
                "pages_scraped": pages_scraped_count,  # Include potentially updated count
                "progress": {
                    "stage": "processing_content",
                    "details": "📝 Processing content for AI understanding",
                    "percent": 65
                },
            },
        )

        # 3. Process JSON profile to text
        text_to_add = data_processor.extract_text_from_json(business_profile)
        if not text_to_add or not text_to_add.strip():
            logger.warning(
                f"[Background Task] No text extracted from scraped JSON profile for KB '{kb_id}', URL '{url}'. KB not populated."
            )
            current_status = "failed"
            db_manager.update_scrape_status(
                kb_id,
                {
                    "status": current_status,
                    "submitted_url": url,
                    "error": "No text content extracted from scraped profile",
                    "progress": {
                        "stage": "failed",
                        "details": "No text extracted from profile",
                        "percent": 0
                    },
                },
            )
            return  # Stop processing

        logger.info(
            f"[Background Task] Extracted {len(text_to_add)} characters from profile for KB '{kb_id}'."
        )

        # Update status before creating embeddings
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,  # Still 'processing'
                "submitted_url": url,
                "pages_scraped": pages_scraped_count,
                "progress": {
                    "stage": "creating_embeddings",
                    "details": "🧠 Building AI brain with vector embeddings",
                    "percent": 80
                },
            },
        )

        # 4. Add text to Knowledge Base
        # Extract domain name for source_name
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        source_name = f"{parsed_url.netloc} - {pages_scraped_count} pages"
        
        # Update status when finalizing
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,  # Still 'processing'
                "submitted_url": url,
                "pages_scraped": pages_scraped_count,
                "progress": {
                    "stage": "finalizing_kb",
                    "details": "🔗 Connecting knowledge for easy retrieval",
                    "percent": 90
                },
            },
        )
        
        # ------------------------------------------------------------------
        # 4-B. Add text to Knowledge Base (can take a while ‑ embeddings)
        # Run add_to_kb in a background thread and emit heartbeat updates so
        # the UI keeps moving from 90 % → 99 % while we wait.
        # ------------------------------------------------------------------

        try:
            add_future = asyncio.create_task(
                asyncio.to_thread(
                    kb_manager.add_to_kb,
                    kb_id,
                    text_to_add,
                    metadata={"pages_scraped": pages_scraped_count},
                    knowledge_source="website",
                    source_name=source_name,
                    source_url=url,
                )
            )

            heartbeat_percent = 91
            while not add_future.done():
                # Send heartbeat (max 99 %)
                db_manager.update_scrape_status(
                    kb_id,
                    {
                        "status": current_status,
                        "submitted_url": url,
                        "pages_scraped": pages_scraped_count,
                        "total_pages": pages_scraped_count,
                        "progress": {
                            "stage": "finalizing_kb",
                            "details": f"🔗 Finalizing knowledge base ({heartbeat_percent}%)",
                            "percent": heartbeat_percent,
                        },
                    },
                )
                # Wait a bit before next ping
                await asyncio.sleep(5)
                heartbeat_percent = min(heartbeat_percent + 2, 99)

            # When finished, get result / raise exception if failed in thread
            add_success = await add_future
        except Exception as e:
            logger.error(
                f"[Background Task] Failed to add content to KB due to connection issue: {e}"
            )
            add_success = False
        
        if add_success:
            logger.info(
                f"[Background Task] Successfully populated KB '{kb_id}' with scraped content from URL '{url}'."
            )
            
            # Update knowledge_sources table with connection retry
            try:
                # Try to get bot_id from kb_id
                bot_response = supabase.table("bots").select("id").eq("kb_id", kb_id).execute()
                
                if bot_response.data and len(bot_response.data) > 0:
                    bot_id = bot_response.data[0]["id"]
                    
                    # Create knowledge source entry with scraped URL and summary
                    knowledge_source_data = {
                        "bot_id": bot_id,
                        "source_type": "website",
                        "content": f"Scraped from: {url} - {pages_scraped_count} pages processed"
                    }
                    
                    # Insert into knowledge_sources table
                    supabase.table("knowledge_sources").insert(knowledge_source_data).execute()
                    logger.info(f"[Background Task] Updated knowledge_sources table for bot_id '{bot_id}'")
                else:
                    logger.warning(f"[Background Task] No bot found for kb_id '{kb_id}', skipping knowledge_sources update")
                    
            except Exception as e:
                logger.error(f"[Background Task] Failed to update knowledge_sources table: {str(e)}")
                # Don't fail the whole process if knowledge_sources update fails
            
            current_status = "completed"
            # Try multiple times to ensure final status is saved with exponential backoff
            final_update_success = False
            for attempt in range(5):  # Increased from 3 to 5 attempts
                try:
                    success = db_manager.update_scrape_status(
                        kb_id,
                        {
                            "status": current_status,
                            "submitted_url": url,
                            "pages_scraped": pages_scraped_count,  # Final count
                            "total_pages": pages_scraped_count,  # Ensure total_pages is set
                            "progress": {
                                "stage": "completed",
                                "details": "🚀 AI agent ready! Knowledge base created successfully",
                                "chars_added": len(text_to_add),
                                "profile_keys": list(business_profile.keys()),
                                "percent": 100
                            },
                        },
                    )
                    if success:
                        logger.info(f"Successfully updated final status to completed for KB {kb_id}")
                        final_update_success = True
                        break
                    else:
                        logger.warning(f"Attempt {attempt + 1}: update_scrape_status returned False for KB {kb_id}")
                except Exception as e:
                    logger.error(f"Attempt {attempt + 1} failed to update final status: {e}")
                    if attempt == 4:  # Last attempt
                        logger.error(f"Failed to update final status after 5 attempts for KB {kb_id}")
                    else:
                        # Exponential backoff: 1s, 2s, 4s, 8s
                        wait_time = 2 ** attempt
                        await asyncio.sleep(wait_time)
            
            # If all attempts failed, try one final direct database update
            if not final_update_success:
                logger.warning(f"All retry attempts failed, trying direct database update for KB {kb_id}")
                try:
                    # Re-use the module-level Supabase client (avoid shadowing)
                    direct_result = supabase.table('scraping_status').upsert({
                        'kb_id': kb_id,
                        'status': 'completed',
                        'submitted_url': url,
                        'pages_scraped': pages_scraped_count,
                        'total_pages': pages_scraped_count,
                        'progress_data': {
                            "stage": "completed",
                            "details": "🚀 AI agent ready! Knowledge base created successfully",
                            "percent": 100
                        }
                    }).execute()
                    if direct_result.data:
                        logger.info(f"Direct database update successful for KB {kb_id}")
                        final_update_success = True
                except Exception as e:
                    logger.error(f"Direct database update also failed for KB {kb_id}: {e}")
            
            # Log final status for debugging
            if final_update_success:
                logger.info(f"[Background Task] FINAL STATUS: KB '{kb_id}' completed successfully with {pages_scraped_count} pages")
            else:
                logger.error(f"[Background Task] CRITICAL: Failed to update final completion status for KB '{kb_id}'")
        else:
            logger.error(
                f"[Background Task] Failed to add scraped content to KB '{kb_id}' from URL '{url}'."
            )
            current_status = "failed"
            db_manager.update_scrape_status(
                kb_id,
                {
                    "status": current_status,
                    "submitted_url": url,
                    "error": "Failed to add extracted content to knowledge base",
                    "progress": {
                        "stage": "failed",
                        "details": "Failed to add content to KB",
                        "percent": 0
                    },
                },
            )

    except Exception as e:
        logger.exception(
            f"[Background Task] Unhandled exception during scrape/populate for KB '{kb_id}', URL '{url}': {e}"
        )
        # Ensure status reflects failure
        current_status = "failed"
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,
                "submitted_url": url,
                "error": f"Unhandled exception: {str(e)}",
                "progress": {
                    "stage": "failed",
                    "details": f"Unhandled exception: {str(e)}",
                    "percent": 0
                },
            },
        )

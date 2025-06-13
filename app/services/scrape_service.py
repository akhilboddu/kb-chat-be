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
    db_manager.update_scrape_status(
        kb_id,
        {
            "status": current_status,
            "submitted_url": url,
            "pages_scraped": 0,
            "total_pages": max_pages
            if max_pages
            else config.get("MAX_INTERNAL_PAGES", 15),
            "progress": {"stage": "starting", "details": "Initializing scraper"},
        },
    )

    try:
        # 1. Run the scraper
        scrape_result = await scraper.scrape_website(
            url, max_pages=max_pages
        )  # Pass max_pages override

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
                        "details": f"Scraped {pages_scraped_count} pages",
                    },
                },
            )

        # 2. Extract the business profile
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
                    },
                },
            )
            return  # Stop processing

        logger.info(
            f"[Background Task] Scrape successful for KB '{kb_id}', URL '{url}'. Profile keys: {list(business_profile.keys())}"
        )

        # Update status before processing
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,  # Still 'processing'
                "submitted_url": url,
                "pages_scraped": pages_scraped_count,  # Include potentially updated count
                "progress": {
                    "stage": "processing_profile",
                    "details": "Extracting text from profile",
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
                    },
                },
            )
            return  # Stop processing

        logger.info(
            f"[Background Task] Extracted {len(text_to_add)} characters from profile for KB '{kb_id}'."
        )

        # Update status before adding to KB
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,  # Still 'processing'
                "submitted_url": url,
                "progress": {
                    "stage": "populating_kb",
                    "details": "Adding extracted text to knowledge base",
                },
            },
        )

        # 4. Add text to Knowledge Base
        add_success = kb_manager.add_to_kb(kb_id, text_to_add, knowledge_source="website")
        if add_success:
            logger.info(
                f"[Background Task] Successfully populated KB '{kb_id}' with scraped content from URL '{url}'."
            )
            
            # Update knowledge_sources table
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
            db_manager.update_scrape_status(
                kb_id,
                {
                    "status": current_status,
                    "submitted_url": url,
                    "pages_scraped": pages_scraped_count,  # Final count
                    "progress": {
                        "stage": "completed",
                        "details": "Successfully added content to knowledge base",
                        "chars_added": len(text_to_add),
                        "profile_keys": list(business_profile.keys()),
                    },
                },
            )
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
                },
            },
        )

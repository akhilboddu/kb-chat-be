import asyncio
import logging
from typing import Optional

from app.core import config, db_manager, kb_manager, scraper, data_processor

logger = logging.getLogger(__name__)


async def run_scrape_and_populate(kb_id: str, url: str, max_pages: Optional[int]):
    """Run the scraper and populate the knowledge base with the results."""
    current_status = "processing"
    
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

        # Update pages scraped from metadata
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
        if not business_profile:
            error_detail = "Missing business profile"
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
                    "details": "Extracting structured content from profile",
                },
            },
        )

        # 3. Process JSON profile to text (now only using structured content)
        text_to_add = data_processor.extract_text_from_json(business_profile)
        if not text_to_add or not text_to_add.strip():
            error_detail = "No structured content extracted from profile"
            logger.error(
                f"[Background Task] Text extraction failed for KB '{kb_id}', URL '{url}'. Error: {error_detail}"
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
                        "details": f"Text extraction failed: {error_detail}",
                    },
                },
            )
            return  # Stop processing

        # 4. Add to knowledge base
        success = kb_manager.add_to_kb(
            kb_id,
            text_to_add,
            metadata={
                "source": "web_scrape",
                "url": url,
                "scrape_time": scrape_result["scrape_metadata"].get("scrape_time"),
                "content_type": "structured"  # Indicate that this is structured content
            },
        )

        if not success:
            error_detail = "Failed to add content to knowledge base"
            logger.error(
                f"[Background Task] KB update failed for KB '{kb_id}', URL '{url}'. Error: {error_detail}"
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
                        "details": f"KB update failed: {error_detail}",
                    },
                },
            )
            return  # Stop processing

        # 5. Update final status
        current_status = "completed"
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,
                "submitted_url": url,
                "pages_scraped": pages_scraped_count,
                "progress": {
                    "stage": "completed",
                    "details": f"Successfully processed {pages_scraped_count} pages",
                },
            },
        )

        logger.info(
            f"[Background Task] Successfully completed scrape and KB update for KB '{kb_id}', URL '{url}'"
        )

    except Exception as e:
        logger.exception(
            f"[Background Task] Unexpected error during scrape for KB '{kb_id}', URL '{url}': {str(e)}"
        )
        current_status = "failed"
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": current_status,
                "submitted_url": url,
                "error": str(e),
                "progress": {
                    "stage": "failed",
                    "details": f"Unexpected error: {str(e)}",
                },
            },
        )

from fastapi import APIRouter, HTTPException, BackgroundTasks, status, Depends
import logging
import os

from app.core import supabase_metadata_manager as db_manager, config
from app.models.scrape import (
    ScrapeURLRequest,
    ScrapeInitiatedResponse,
    ScrapeStatusResponse,
)
from app.services.scrape_service import run_scrape_and_populate
from app.tasks.scrape import run_scrape_task
from app.utils.cookie_auth import require_cookie_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["scraping"], dependencies=[Depends(require_cookie_auth)])


@router.post(
    "/agents/{kb_id}/scrape-url",
    response_model=ScrapeInitiatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def scrape_url_and_populate_kb(
    kb_id: str, request: ScrapeURLRequest, background_tasks: BackgroundTasks
):
    """
    Initiate scraping of a URL to populate a knowledge base.
    The scraping happens in the background.
    """
    try:
        # --------------------------------------------------------------
        # TEMP: Hard-force the scraper to fetch only 3 pages to speed up
        # local testing, regardless of what the client sends.
        # Remove this block when you're ready for full crawls.
        # --------------------------------------------------------------
        request.max_pages = 3

        # Initialize scraping status
        initial_status = {
            "status": "processing",
            "submitted_url": str(request.url),
            "pages_scraped": 0,
            "total_pages": request.max_pages
            if request.max_pages
            else config.get("MAX_INTERNAL_PAGES", 15),
            "progress": {"stage": "initialized", "details": "Starting scrape process"},
        }
        print(initial_status)

        # Check if we should use Celery
        use_celery = os.getenv("USE_CELERY", "true").lower() == "true"
        
        if use_celery:
            # Queue task with Celery
            result = run_scrape_task.apply_async(
                args=[kb_id, str(request.url), request.max_pages]
            )
            # Add Celery task ID to status
            initial_status["celery_id"] = result.id
            logger.info(f"Queued scrape task with Celery ID: {result.id}")

        # Update initial status
        if not db_manager.update_scrape_status(kb_id, initial_status):
            raise HTTPException(
                status_code=500, detail="Failed to initialize scraping status"
            )

        # If not using Celery, use BackgroundTasks as fallback
        if not use_celery:
            background_tasks.add_task(
                run_scrape_and_populate,
                kb_id=kb_id,
                url=str(request.url),
                max_pages=request.max_pages,
            )
            logger.info("Using BackgroundTasks for scraping (Celery disabled)")

        return ScrapeInitiatedResponse(
            kb_id=kb_id,
            status="processing",
            message="Scraping initiated in background",
            submitted_url=str(request.url),
        )

    except Exception as e:
        logger.error(f"Error initiating scrape for KB {kb_id}: {e}")
        # Update status to failed if initialization fails
        db_manager.update_scrape_status(
            kb_id,
            {
                "status": "failed",
                "submitted_url": str(request.url),
                "error": str(e),
                "progress": {
                    "stage": "failed",
                    "details": f"Failed to initialize scrape: {str(e)}",
                },
            },
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to initiate scraping: {str(e)}"
        )


@router.get("/agents/{kb_id}/scrape-status", response_model=ScrapeStatusResponse)
async def get_scrape_status(kb_id: str):
    """
    Get the current status of a scraping operation for a specific KB.
    """
    try:
        status = db_manager.get_scrape_status(kb_id)
        if not status:
            # Return a "not found" status instead of throwing 404
            # This allows the frontend polling to handle it gracefully
            return ScrapeStatusResponse(
                kb_id=kb_id,
                status="not_found",
                submitted_url="",
                pages_scraped=0,
                total_pages=0,
                progress={
                    "stage": "not_found",
                    "details": "No scraping operation found"
                }
            )
        return ScrapeStatusResponse(**status)
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error retrieving scrape status for KB {kb_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve scraping status: {str(e)}"
        )


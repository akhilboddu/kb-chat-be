from fastapi import APIRouter, HTTPException, BackgroundTasks, status
import logging

from app.core import db_manager, config
from app.models.scrape import (
    ScrapeURLRequest,
    ScrapeInitiatedResponse,
    ScrapeStatusResponse,
)
from app.services.scrape_service import run_scrape_and_populate

logger = logging.getLogger(__name__)
router = APIRouter(tags=["scraping"])


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

        # Update initial status
        if not db_manager.update_scrape_status(kb_id, initial_status):
            raise HTTPException(
                status_code=500, detail="Failed to initialize scraping status"
            )

        # Add the background task
        background_tasks.add_task(
            run_scrape_and_populate,
            kb_id=kb_id,
            url=str(request.url),
            max_pages=request.max_pages,
        )

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
            raise HTTPException(
                status_code=404, detail=f"No scraping operation found for KB {kb_id}"
            )
        return ScrapeStatusResponse(**status)
    except Exception as e:
        logger.error(f"Error retrieving scrape status for KB {kb_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve scraping status: {str(e)}"
        )


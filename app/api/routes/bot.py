from fastapi import APIRouter, HTTPException, Query
from .scrape import scrape_url_and_populate_kb
from app.models.scrape import ScrapeURLRequest

from app.models.base import StatusResponse
from app.models.bot import (
    AddKnowledgeRequest,
)
from app.models.scrape import ScrapeStatusResponse
from app.core import kb_manager, db_manager
from app.core.supabase_client import supabase
from fastapi import BackgroundTasks
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
from app.models.crm import CRMEntry, PaginatedCRMResponse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

router = APIRouter(prefix="/bots", tags=["bots"])

# New model for demo bot requests
class DemoBotRequest(BaseModel):
    url: HttpUrl
    name: Optional[str] = None
    description: Optional[str] = None
    max_pages: Optional[int] = 1


@router.post("/{bot_id}/knowledge", response_model=StatusResponse)
async def bot_knowledge_endpoint(bot_id: str, request: AddKnowledgeRequest):
    """
    Endpoint for adding verified knowledge to the bot's KB.
    """
    print(f"Received knowledge addition for bot_id: {bot_id}")

    if not request.knowledge_text or not request.knowledge_text.strip():
        raise HTTPException(status_code=400, detail="Knowledge text cannot be empty")

    try:
        # First, get the kb_id from the bot
        bot_response = supabase.table("bots").select("kb_id").eq("id", bot_id).execute()

        if not bot_response.data or len(bot_response.data) == 0:
            raise HTTPException(
                status_code=404, detail=f"Bot with ID {bot_id} not found"
            )

        kb_id = bot_response.data[0]["kb_id"]

        # Add to knowledge base with metadata
        success = kb_manager.add_to_kb(kb_id=kb_id, text_to_add=request.knowledge_text)

        if not success:
            print(f"kb_manager.add_to_kb returned False for KB {kb_id}")
            raise HTTPException(
                status_code=500,
                detail="Failed to add knowledge to the knowledge base (internal KB error)",
            )

        # Log the KB update
        log_success = db_manager.log_kb_update(kb_id, request.knowledge_text)
        if not log_success:
            # Log warning but don't fail the request
            print(f"Warning: Failed to log KB update for {kb_id}")

        # Update the knowledge sources table
        supabase.table("knowledge_sources").insert(
            {
                "bot_id": bot_id,
                "source_type": "human conversation",
                "content": request.knowledge_text,
            }
        ).execute()

        return StatusResponse(
            status="success",
            message="Knowledge successfully added to the bot's knowledge base",
        )

    except HTTPException as http_exc:
        # Re-raise known HTTP exceptions
        raise http_exc
    except Exception as e:
        # Catch potential errors during metadata creation or kb_manager call
        print(f"Error adding knowledge to KB for bot {bot_id}: {e}")
        import traceback

        traceback.print_exc()
        # Check if the error message indicates a metadata issue specifically
        if "Expected metadata value to be a str, int, float or bool" in str(e):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to add knowledge to knowledge base: Metadata type error - {str(e)}",
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to add knowledge to knowledge base: {str(e)}",
            )


@router.post("/{bot_id}/scrape-url", response_model=StatusResponse)
async def bot_scrape_url_endpoint(
    bot_id: str, request: ScrapeURLRequest, background_tasks: BackgroundTasks
):
    """
    Endpoint for scraping a URL and adding the content to the bot's KB.
    """
    print(f"Received scrape URL request for bot_id: {bot_id}")
    print(f"Request: {request}")

    # Get the kb_id from the bot
    bot_response = supabase.table("bots").select("kb_id").eq("id", bot_id).execute()
    if not bot_response.data or len(bot_response.data) == 0:
        raise HTTPException(status_code=404, detail=f"Bot with ID {bot_id} not found")

    kb_id = bot_response.data[0]["kb_id"]

    response = await scrape_url_and_populate_kb(kb_id, request, background_tasks)

    if response:
        return StatusResponse(
            status="success",
            message="Scrape URL request received",
        )
    else:
        return StatusResponse(status="error", message="Scrape URL request failed")


@router.post("/{bot_id}/scrape-url-status", response_model=ScrapeStatusResponse)
async def bot_scrape_url_status_endpoint(bot_id: str):
    """
    Endpoint for checking the status of a scrape URL request.
    """
    pass


@router.get("/crm/{bot_id}", response_model=PaginatedCRMResponse)
def get_crm_entries_for_bot(
    bot_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100)
):
    start = (page - 1) * page_size
    end = start + page_size - 1
    # Get total count
    count_response = supabase.table("bot_crms").select("id", count="exact").eq("bot_id", bot_id).execute()
    total_count = count_response.count if hasattr(count_response, "count") else 0
    # Get paginated data
    response = supabase.table("bot_crms").select("*").eq("bot_id", bot_id).order("created_at", desc=True).range(start, end).execute()
    crms = response.data or []
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
    return PaginatedCRMResponse(
        crms=crms,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("/demo-bot", response_model=StatusResponse)
async def create_demo_bot(
    request: DemoBotRequest,
    background_tasks: BackgroundTasks
):
    """
    Creates a new demo bot for a given URL, including:
    1. Extracts domain from URL
    2. Checks if demo bot already exists
    3. If exists and older than a week, recreates KB
    4. If doesn't exist, creates new KB and demo bot
    5. Initiates scraping of the URL
    """
    try:
        # Extract domain from URL
        parsed_url = urlparse(str(request.url))
        domain = parsed_url.netloc.replace('www.', '')
        
        # Check if demo bot already exists
        existing_bot = supabase.table("demo_bots").select("*").eq("url", domain).execute()
        
        if existing_bot.data:
            bot = existing_bot.data[0]
            created_at = datetime.fromisoformat(bot['created_at'].replace('Z', '+00:00'))
            one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            
            if created_at < one_week_ago:
                # Bot is older than a week, recreate KB
                old_kb_id = bot['kb_id']
                
                # Delete old knowledge base
                kb_manager.delete_kb(old_kb_id)
                
                # Create new knowledge base
                kb_id = f"demo_{hash(domain)}"
                kb_collection = kb_manager.create_or_get_kb(
                    kb_id=kb_id,
                    name=f"Demo KB for {domain}"
                )
                
                if not kb_collection:
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to create new knowledge base"
                    )
                
                # Update demo bot record with new kb_id
                supabase.table("demo_bots").update({
                    "kb_id": kb_id,
                    "status": "processing",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }).eq("url", domain).execute()
                
                # Start scraping in background
                scrape_request = ScrapeURLRequest(
                    url=str(request.url),
                    max_pages=request.max_pages
                )
                background_tasks.add_task(
                    scrape_url_and_populate_kb,
                    kb_id,
                    scrape_request,
                    background_tasks
                )
                
                return StatusResponse(
                    status="success",
                    message="Demo bot recreated and scraping started"
                )
            else:
                # Bot is newer than a week, return existing KB
                return StatusResponse(
                    status="success",
                    message="Using existing demo bot"
                )
        
        # No existing bot found, create new one
        kb_id = f"demo_{hash(domain)}"
        
        # Create new knowledge base
        kb_collection = kb_manager.create_or_get_kb(
            kb_id=kb_id,
            name=f"Demo KB for {domain}"
        )
        
        if not kb_collection:
            raise HTTPException(
                status_code=500,
                detail="Failed to create knowledge base"
            )
        
        # Create demo bot entry
        demo_bot_data = {
            "url": domain,
            "name": request.name or f"Demo Bot for {domain}",
            "description": request.description,
            "kb_id": kb_id,
            "status": "processing",
            "max_pages": request.max_pages,
            "metadata": {
                "created_via": "demo_bot_endpoint",
                "initial_scrape": True
            }
        }
        
        demo_bot_response = supabase.table("demo_bots").insert(demo_bot_data).execute()
        
        if not demo_bot_response.data:
            # Clean up the KB if demo bot creation fails
            kb_manager.delete_kb(kb_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to create demo bot entry"
            )
        
        # Start scraping in background
        scrape_request = ScrapeURLRequest(
            url=str(request.url),
            max_pages=request.max_pages
        )
        background_tasks.add_task(
            scrape_url_and_populate_kb,
            kb_id,
            scrape_request,
            background_tasks
        )
        
        return StatusResponse(
            status="success",
            message="Demo bot created and scraping started"
        )
        
    except Exception as e:
        print(f"Error creating demo bot: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create demo bot: {str(e)}"
        )

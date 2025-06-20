from fastapi import APIRouter, HTTPException, Query
from .scrape import scrape_url_and_populate_kb
from app.models.scrape import ScrapeURLRequest

from app.models.base import StatusResponse
from app.models.bot import (
    AddKnowledgeRequest,
)
from app.models.scrape import ScrapeStatusResponse
from app.core import kb_manager, supabase_metadata_manager as db_manager
from app.core.supabase_client import supabase
from fastapi import BackgroundTasks
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
from app.models.crm import CRMEntry, PaginatedCRMResponse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from dateutil.parser import isoparse  # more tolerant ISO-8601 parser
import hashlib

router = APIRouter(prefix="/bots", tags=["bots"])

# New model for demo bot requests
class DemoBotRequest(BaseModel):
    url: HttpUrl
    name: Optional[str] = None
    description: Optional[str] = None
    max_pages: Optional[int] = 3  # Changed default from 1 to 3

# New model for demo bot metadata response
class DemoBotMetaResponse(BaseModel):
    kb_id: str
    status: str
    name: Optional[str] = None
    created_at: Optional[str] = None


# KB Management Compatibility Endpoints
@router.get("/{bot_id}/kb/sources")
async def list_bot_kb_sources(bot_id: str):
    """List all knowledge sources for a bot's KB - compatibility endpoint"""
    try:
        # Get the kb_id from bot_id
        bot_response = supabase.table("bots").select("kb_id").eq("id", bot_id).execute()
        
        if not bot_response.data or len(bot_response.data) == 0:
            raise HTTPException(status_code=404, detail=f"Bot with ID {bot_id} not found")
        
        kb_id = bot_response.data[0]["kb_id"]
        
        # Query the view using kb_id
        sources = supabase.table("vw_kb_sources")\
            .select("*")\
            .eq("kb_id", kb_id)\
            .order("last_updated", desc=True)\
            .execute()
        
        return {"sources": sources.data or []}
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error listing KB sources for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list KB sources: {str(e)}")

@router.get("/{bot_id}/kb/documents")
async def list_bot_kb_documents(
    bot_id: str,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0)
):
    """List documents for a bot's KB with filtering and search - compatibility endpoint"""
    try:
        # Get the kb_id from bot_id
        bot_response = supabase.table("bots").select("kb_id").eq("id", bot_id).execute()
        
        if not bot_response.data or len(bot_response.data) == 0:
            raise HTTPException(status_code=404, detail=f"Bot with ID {bot_id} not found")
        
        kb_id = bot_response.data[0]["kb_id"]
        
        query = supabase.table("knowledge_base_documents")\
            .select("id, document_id, content, source_type, source_name, source_url, created_at", count="exact")\
            .eq("kb_id", kb_id)
        
        if source_name:
            query = query.eq("source_name", source_name)
        if source_type:
            query = query.eq("source_type", source_type)
        if search:
            query = query.ilike("content", f"%{search}%")
        
        query = query.order("created_at", desc=True)
        result = query.range(offset, offset + limit - 1).execute()
        
        return {
            "documents": result.data or [],
            "total": result.count or 0,
            "limit": limit,
            "offset": offset
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error listing KB documents for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list KB documents: {str(e)}")

@router.post("/{bot_id}/kb/optimize")
async def optimize_bot_knowledge_base(bot_id: str):
    """AI-powered knowledge base optimization for a bot - compatibility endpoint"""
    try:
        # Get the kb_id from bot_id
        bot_response = supabase.table("bots").select("kb_id").eq("id", bot_id).execute()
        
        if not bot_response.data or len(bot_response.data) == 0:
            raise HTTPException(status_code=404, detail=f"Bot with ID {bot_id} not found")
        
        kb_id = bot_response.data[0]["kb_id"]
        
        # Import and call the optimize function from kb router
        from app.api.routes.kb import optimize_knowledge_base
        
        # Call the optimization function with the kb_id (treating it as agent_id)
        return await optimize_knowledge_base(kb_id)
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error optimizing KB for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to optimize KB: {str(e)}")

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
        from datetime import datetime
        source_name = f"Human input - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        success = kb_manager.add_to_kb(
            kb_id=kb_id, 
            text_to_add=request.knowledge_text, 
            knowledge_source="human conversation",
            source_name=source_name
        )

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
        # Normalize URL - add protocol if missing
        url = str(request.url)
        if not url.startswith('http'):
            url = f"https://{url}"
            
        # Extract domain from URL
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.replace('www.', '')
        
        # Check if demo bot already exists
        existing_bot = supabase.table("demo_bots").select("*").eq("url", domain).execute()
        
        if existing_bot.data:
            bot = existing_bot.data[0]
            try:
                # Supabase may return timestamps with varying micro-second precision; use dateutil for robustness
                created_at = isoparse(bot['created_at'])
            except Exception:
                # Fallback to naive isoformat parsing
                created_at = datetime.fromisoformat(bot['created_at'].replace('Z', '+00:00'))
            one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            
            if created_at < one_week_ago:
                # Bot is older than a week, recreate KB
                old_kb_id = bot['kb_id']
                
                # Delete old knowledge base
                kb_manager.delete_kb(old_kb_id)
                
                # Create new knowledge base with deterministic ID
                kb_id = f"demo_{hashlib.sha1(domain.encode()).hexdigest()[:10]}"
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
                    url=url,  # Use normalized URL
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
        
        # No existing bot found, create new one with deterministic ID
        kb_id = f"demo_{hashlib.sha1(domain.encode()).hexdigest()[:10]}"
        
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
        
        # Use upsert to handle potential race conditions since url has unique constraint
        demo_bot_response = supabase.table("demo_bots").upsert(
            demo_bot_data,
            on_conflict="url"
        ).execute()
        
        if not demo_bot_response.data:
            # Clean up the KB if demo bot creation fails
            kb_manager.delete_kb(kb_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to create demo bot entry"
            )
        
        # Start scraping in background
        scrape_request = ScrapeURLRequest(
            url=url,  # Use normalized URL
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


@router.delete("/{bot_id}", response_model=StatusResponse)
async def delete_bot(bot_id: str):
    """
    Delete a bot and all its associated knowledge base data.
    
    This endpoint will:
    1. Get the bot's kb_id from the bots table
    2. Delete all knowledge_base_documents for that kb_id
    3. Delete the knowledge_bases entry for that kb_id
    4. Delete the bot record itself
    5. Clean up related data (conversations, messages, CRM entries, etc.)
    """
    try:
        print(f"Starting deletion process for bot_id: {bot_id}")
        
        # First, get the bot and its kb_id
        bot_response = supabase.table("bots").select("kb_id, name").eq("id", bot_id).execute()
        
        if not bot_response.data or len(bot_response.data) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Bot with ID {bot_id} not found"
            )
        
        kb_id = bot_response.data[0]["kb_id"]
        bot_name = bot_response.data[0].get("name", "Unknown")
        
        print(f"Found bot '{bot_name}' with kb_id: {kb_id}")
        
        # Delete knowledge base using kb_manager (this handles both tables)
        try:
            kb_deleted = kb_manager.delete_kb(kb_id)
            if kb_deleted:
                print(f"Successfully deleted knowledge base: {kb_id}")
            else:
                print(f"Warning: kb_manager.delete_kb returned False for {kb_id}")
        except Exception as kb_error:
            print(f"Error deleting knowledge base {kb_id}: {str(kb_error)}")
            # Continue with other deletions even if KB deletion fails
        
        # Delete related data from other tables
        deleted_items = {}
        
        # Delete conversations and their messages
        try:
            conversations_response = supabase.table("conversations").select("id").eq("bot_id", bot_id).execute()
            conversation_ids = [conv["id"] for conv in conversations_response.data or []]
            
            if conversation_ids:
                # Delete messages for these conversations
                for conv_id in conversation_ids:
                    messages_delete = supabase.table("messages").delete().eq("conversation_id", conv_id).execute()
                    deleted_items["messages"] = deleted_items.get("messages", 0) + len(messages_delete.data or [])
                
                # Delete conversations
                conversations_delete = supabase.table("conversations").delete().eq("bot_id", bot_id).execute()
                deleted_items["conversations"] = len(conversations_delete.data or [])
            
        except Exception as conv_error:
            print(f"Error deleting conversations: {str(conv_error)}")
        
        # Delete CRM entries
        try:
            crm_delete = supabase.table("bot_crms").delete().eq("bot_id", bot_id).execute()
            deleted_items["crm_entries"] = len(crm_delete.data or [])
        except Exception as crm_error:
            print(f"Error deleting CRM entries: {str(crm_error)}")
        
        # Delete knowledge sources
        try:
            knowledge_sources_delete = supabase.table("knowledge_sources").delete().eq("bot_id", bot_id).execute()
            deleted_items["knowledge_sources"] = len(knowledge_sources_delete.data or [])
        except Exception as ks_error:
            print(f"Error deleting knowledge sources: {str(ks_error)}")
        
        # Delete WhatsApp configurations
        try:
            whatsapp_delete = supabase.table("whatsapp_configs").delete().eq("bot_id", bot_id).execute()
            deleted_items["whatsapp_configs"] = len(whatsapp_delete.data or [])
        except Exception as wa_error:
            print(f"Error deleting WhatsApp configs: {str(wa_error)}")
        
        # Delete handover requests (via conversations)
        try:
            if conversation_ids:
                for conv_id in conversation_ids:
                    handover_delete = supabase.table("handover_requests").delete().eq("conversation_id", conv_id).execute()
                    deleted_items["handover_requests"] = deleted_items.get("handover_requests", 0) + len(handover_delete.data or [])
        except Exception as ho_error:
            print(f"Error deleting handover requests: {str(ho_error)}")
        
        # Finally, delete the bot itself
        try:
            bot_delete = supabase.table("bots").delete().eq("id", bot_id).execute()
            if not bot_delete.data:
                raise Exception("Bot deletion returned no data")
            deleted_items["bot"] = 1
        except Exception as bot_error:
            print(f"Error deleting bot: {str(bot_error)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete bot record: {str(bot_error)}"
            )
        
        # Clean up SQLite metadata if it exists
        try:
            # This might not exist in the new system, but try anyway
            db_manager.clear_conversation_history(kb_id)
            print(f"Cleared SQLite conversation history for kb_id: {kb_id}")
        except Exception as sqlite_error:
            print(f"Note: SQLite cleanup failed (this may be expected): {str(sqlite_error)}")
        
        # Create summary message
        summary_parts = [f"Bot '{bot_name}' and knowledge base '{kb_id}' deleted successfully"]
        if deleted_items:
            details = []
            for item_type, count in deleted_items.items():
                if count > 0:
                    details.append(f"{count} {item_type}")
            if details:
                summary_parts.append(f"Also removed: {', '.join(details)}")
        
        summary_message = ". ".join(summary_parts) + "."
        
        print(f"Deletion completed: {summary_message}")
        
        return StatusResponse(
            status="success",
            message=summary_message
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(f"Error during bot deletion: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete bot: {str(e)}"
        )

# New endpoint to get demo bot metadata
@router.get("/demo-bot/meta")
async def get_demo_bot_meta(url: str) -> DemoBotMetaResponse:
    """
    Get metadata for a demo bot by URL (read-only, no side effects)
    """
    try:
        # Extract domain from URL - handle both with and without protocol
        if url.startswith('http'):
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace('www.', '')
        else:
            # Handle cases where URL doesn't have protocol
            # Clean up the URL and extract domain
            clean_url = url.replace('www.', '')
            domain = clean_url.split('/')[0]
        
        # Look up demo bot
        existing_bot = supabase.table("demo_bots").select("*").eq("url", domain).execute()
        
        if not existing_bot.data:
            raise HTTPException(
                status_code=404,
                detail=f"No demo bot found for URL: {domain}"
            )
        
        bot = existing_bot.data[0]
        
        return DemoBotMetaResponse(
            kb_id=bot['kb_id'],
            status=bot.get('status', 'unknown'),
            name=bot.get('name'),
            created_at=bot.get('created_at')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting demo bot meta: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get demo bot metadata: {str(e)}"
        )

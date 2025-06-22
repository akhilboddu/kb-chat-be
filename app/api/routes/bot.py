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
from typing import List, Optional, Dict, Any
from app.models.crm import CRMEntry, PaginatedCRMResponse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from dateutil.parser import isoparse  # more tolerant ISO-8601 parser

router = APIRouter(prefix="/bots", tags=["bots"])

# New model for demo bot requests
class DemoBotRequest(BaseModel):
    url: HttpUrl
    name: Optional[str] = None
    description: Optional[str] = None
    max_pages: Optional[int] = 1


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

# --- Web Search Configuration ---

class WebSearchConfigModel(BaseModel):
    is_enabled: bool
    usage_guide: str

@router.get("/{bot_id}/web_search_config", response_model=WebSearchConfigModel)
async def get_web_search_config(bot_id: str):
    """
    Retrieves the web search configuration for a specific bot.
    If no config exists, returns a default configuration.
    """
    try:
        response = supabase.table("web_search_configs").select("*").eq("bot_id", bot_id).single().execute()

        if response.data:
            # Config found, return it
            return WebSearchConfigModel(**response.data)
        else:
            # No config found, return a default config to ensure the frontend works correctly.
            default_config = {
                "is_enabled": False,
                "usage_guide": """Use this tool ONLY when the user's query is DIRECTLY related to your business context and you need current information that's not in your knowledge base.

BUSINESS CONTEXT: {YOUR BUSINESS NAME HERE} - {INDUSTRY} - {YOUR WEBSITE HERE}

APPROPRIATE USES:
- Industry news affecting your products/services
- Current market conditions for your business
- Recent regulatory changes impacting your industry
- Competitor updates relevant to your offerings
- Technology trends affecting your solutions
- Economic factors affecting your customers
- Latest information about your products/services from your website

DO NOT USE FOR: 
- General news unrelated to your business
- Personal queries or entertainment
- Topics outside your industry scope
- Information that doesn't help serve the customer""",
            }
            return WebSearchConfigModel(**default_config)

    except Exception as e:
        # Don't return 404 for 'not found', as we provide a default.
        # Only raise 500 for actual database errors.
        if "Multiple rows returned" in str(e):
             raise HTTPException(status_code=500, detail="Data integrity error: Found multiple web search configurations for this bot.")
        print(f"Error fetching web search config for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred while fetching the web search configuration.")

@router.put("/{bot_id}/web_search_config", response_model=StatusResponse)
async def update_web_search_config(bot_id: str, config: WebSearchConfigModel):
    """
    Updates or creates the web search configuration for a specific bot.
    """
    try:
        db_manager.save_web_search_config(bot_id, config.dict())
        return StatusResponse(
            status="success",
            message="Web search configuration saved successfully."
        )
    except Exception as e:
        print(f"Error saving web search config for bot {bot_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to save web search configuration: {str(e)}")

# --- End Web Search Configuration ---

# --- Lead Scorer Configuration ---

class LeadScorerConfigModel(BaseModel):
    is_enabled: bool
    scoring_guide: str
    inactive_time: int = 3  # Default to 3 hours

@router.get("/{bot_id}/lead_scorer_config", response_model=LeadScorerConfigModel)
async def get_lead_scorer_config(bot_id: str):
    """
    Retrieves the lead scorer configuration for a specific bot.
    If no config exists, returns a default configuration.
    """
    try:
        response = supabase.table("lead_scorer_configs").select("*").eq("bot_id", bot_id).single().execute()

        if response.data:
            # Config found, return it
            return LeadScorerConfigModel(**response.data)
        else:
            # No config found, return a default config to ensure the frontend works correctly.
            default_config = {
                "is_enabled": False,
                "scoring_guide": """Analyze the entire conversation to determine if the user is a qualified lead. A qualified lead shows strong interest, has a clear need for our products/services, and has provided contact information.

SCORING CRITERIA:
- High Interest (5 points): Asks specific questions about pricing, features, or implementation. Uses phrases like "I need this" or "How can I start?".
- Clear Need (3 points): Clearly describes a problem that our product/service solves.
- Contact Info Provided (2 points): User voluntarily provides an email or phone number.
- Budget Mentioned (1 point): User mentions a budget that aligns with our pricing.

OUTPUT FORMAT:
Return a JSON object with two keys: 'score' (the total score) and 'reason' (a brief summary of why the score was given).""",
                "inactive_time": 3,
            }
            return LeadScorerConfigModel(**default_config)

    except Exception as e:
        # Don't return 404 for 'not found', as we provide a default.
        # Only raise 500 for actual database errors.
        if "Multiple rows returned" in str(e):
             raise HTTPException(status_code=500, detail="Data integrity error: Found multiple lead scorer configurations for this bot.")
        print(f"Error fetching lead scorer config for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred while fetching the lead scorer configuration.")

@router.put("/{bot_id}/lead_scorer_config", response_model=StatusResponse)
async def update_lead_scorer_config(bot_id: str, config: LeadScorerConfigModel):
    """
    Updates or creates the lead scorer configuration for a specific bot.
    """
    try:
        db_manager.save_lead_scorer_config(bot_id, config.dict())
        return StatusResponse(
            status="success",
            message="Lead scorer configuration saved successfully."
        )
    except Exception as e:
        print(f"Error saving lead scorer config for bot {bot_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to save lead scorer configuration: {str(e)}")

# --- End Lead Scorer Configuration ---

# --- Follow Up Configuration ---

class FollowUpConfigModel(BaseModel):
    is_enabled: bool
    follow_up_method: str  # 'deskforce' or 'gmail'
    max_follow_ups: int = 3
    stop_on_reply: bool = True

@router.get("/{bot_id}/follow_up_config", response_model=FollowUpConfigModel)
async def get_follow_up_config(bot_id: str):
    """
    Retrieves the follow-up configuration for a specific bot.
    If no config exists, returns a default configuration.
    """
    try:
        response = supabase.table("follow_up_configs").select("*").eq("bot_id", bot_id).single().execute()

        if response.data:
            # Config found, return it
            return FollowUpConfigModel(**response.data)
        else:
            # No config found, return a default config to ensure the frontend works correctly.
            default_config = {
                "is_enabled": False,
                "follow_up_method": "gmail",
                "max_follow_ups": 3,
                "stop_on_reply": True,
            }
            return FollowUpConfigModel(**default_config)

    except Exception as e:
        # Don't return 404 for 'not found', as we provide a default.
        # Only raise 500 for actual database errors.
        if "Multiple rows returned" in str(e):
             raise HTTPException(status_code=500, detail="Data integrity error: Found multiple follow-up configurations for this bot.")
        print(f"Error fetching follow-up config for bot {bot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred while fetching the follow-up configuration.")

@router.put("/{bot_id}/follow_up_config", response_model=StatusResponse)
async def update_follow_up_config(bot_id: str, config: FollowUpConfigModel):
    """
    Updates or creates the follow-up configuration for a specific bot.
    """
    try:
        # Check if bot exists
        bot_response = supabase.table("bots").select("id").eq("id", bot_id).execute()
        if not bot_response.data:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        # Prepare config data for database
        config_data = {
            "bot_id": bot_id,
            "is_enabled": config.is_enabled,
            "follow_up_method": config.follow_up_method,
            "max_follow_ups": config.max_follow_ups,
            "stop_on_reply": config.stop_on_reply,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Upsert configuration
        supabase.table("follow_up_configs").upsert(config_data).execute()
        
        return StatusResponse(
            status="success",
            message="Follow-up configuration saved successfully."
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error saving follow-up config for bot {bot_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to save follow-up configuration: {str(e)}")

# --- End Follow Up Configuration ---

# --- Lead Scoring Endpoint ---

class ScoreSingleLeadRequest(BaseModel):
    conversation_id: str
    bot_id: str

class ScoreSingleLeadResponse(BaseModel):
    status: str
    message: str
    conversation_id: str
    bot_id: str
    lead_score: Optional[int] = None
    contact_info: Optional[str] = None
    scoring_reason: Optional[str] = None

@router.post("/score-single-lead", response_model=ScoreSingleLeadResponse)
async def score_single_lead(request: ScoreSingleLeadRequest):
    """
    Score a single conversation for lead potential and save to bot_crms table.
    
    This endpoint:
    1. Takes a conversation_id and bot_id
    2. Runs the lead scoring agent on the conversation
    3. Saves the results to the bot_crms table
    4. Returns the scoring results
    """
    try:
        from app.utils.lead_scorer import score_single_conversation
        
        print(f"Scoring lead for conversation {request.conversation_id} of bot {request.bot_id}")
        
        # Process the conversation through the lead scoring utility
        result = await score_single_conversation(request.conversation_id, request.bot_id)
        
        if result and result.get("status") == "success":
            # Lead was successfully scored
            return ScoreSingleLeadResponse(
                status="success",
                message="Lead scored successfully and saved to CRM",
                conversation_id=request.conversation_id,
                bot_id=request.bot_id,
                lead_score=result.get("score"),
                contact_info=None,  # This would be extracted from the scoring result if available
                scoring_reason="Lead scoring completed successfully"
            )
        elif result and result.get("status") == "skipped - lead scoring disabled or no config":
            # Lead scoring is disabled or no configuration
            return ScoreSingleLeadResponse(
                status="skipped",
                message="Lead scoring is disabled or not configured for this bot",
                conversation_id=request.conversation_id,
                bot_id=request.bot_id,
                lead_score=None,
                contact_info=None,
                scoring_reason="Lead scoring disabled or no configuration found"
            )
        else:
            # Lead scoring failed
            return ScoreSingleLeadResponse(
                status="failed",
                message="Failed to score lead - conversation may not exist or scoring agent failed",
                conversation_id=request.conversation_id,
                bot_id=request.bot_id,
                lead_score=None,
                contact_info=None,
                scoring_reason="Lead scoring failed"
            )
            
    except Exception as e:
        print(f"Error scoring single lead: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to score lead: {str(e)}"
        )

# --- End Lead Scoring Endpoint ---

# --- Auto Lead Scoring Endpoint ---

class AutoScoreLeadsResponse(BaseModel):
    status: str
    message: str
    total_conversations_found: int
    conversations_processed: int
    successful_scores: int
    failed_scores: int
    skipped_scores: int
    details: List[Dict[str, Any]]

@router.post("/{bot_id}/auto-score-leads", response_model=AutoScoreLeadsResponse)
async def auto_score_leads(bot_id: str):
    """
    Automatically score leads for conversations that have been inactive for the configured time period.
    
    This endpoint:
    1. Gets the lead scorer configuration to determine inactive time threshold
    2. Finds all open conversations for the bot
    3. Filters for conversations with last message older than the configured threshold
    4. Runs lead scoring on those conversations
    5. Saves results to bot_crms table
    6. Returns summary of processing results
    """
    try:
        from app.utils.lead_scorer import process_lead_scoring
        from datetime import datetime, timedelta
        
        print(f"Starting auto lead scoring for bot {bot_id}")
        
        # Get the lead scorer configuration to determine inactive time threshold
        try:
            config_response = supabase.table("lead_scorer_configs").select("*").eq("bot_id", bot_id).single().execute()
            if config_response.data:
                inactive_hours = config_response.data.get("inactive_time", 3)
            else:
                inactive_hours = 3  # Default fallback
        except:
            inactive_hours = 3  # Default fallback
        
        print(f"Using inactive time threshold: {inactive_hours} hours")
        
        # Calculate the cutoff time using configured inactive time
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=inactive_hours)
        cutoff_time_iso = cutoff_time.isoformat()
        
        # Find all open conversations for this bot with last message 3+ hours ago
        conversations_response = supabase.table("conversations").select(
            "id, status, updated_at"
        ).eq("bot_id", bot_id).neq("status", "closed").execute()
        
        if not conversations_response.data:
            return AutoScoreLeadsResponse(
                status="success",
                message="No open conversations found for this bot",
                total_conversations_found=0,
                conversations_processed=0,
                successful_scores=0,
                failed_scores=0,
                skipped_scores=0,
                details=[]
            )
        
        # Filter conversations that haven't had activity for the configured time period
        stale_conversations = []
        for conv in conversations_response.data:
            # Check if conversation has messages and get the last message time
            last_message_response = supabase.table("messages").select(
                "created_at"
            ).eq("conversation_id", conv["id"]).order("created_at", desc=True).limit(1).execute()
            
            if last_message_response.data:
                last_message_time = datetime.fromisoformat(
                    last_message_response.data[0]["created_at"].replace('Z', '+00:00')
                )
                if last_message_time < cutoff_time:
                    stale_conversations.append({
                        "conversation_id": conv["id"],
                        "bot_id": bot_id
                    })
        
        print(f"Found {len(stale_conversations)} conversations inactive for {inactive_hours}+ hours")
        
        if not stale_conversations:
            return AutoScoreLeadsResponse(
                status="success",
                message=f"No conversations found that have been inactive for {inactive_hours}+ hours",
                total_conversations_found=len(conversations_response.data),
                conversations_processed=0,
                successful_scores=0,
                failed_scores=0,
                skipped_scores=0,
                details=[]
            )
        
        # Process lead scoring for the stale conversations
        results = await process_lead_scoring(stale_conversations)
        
        # Close conversations that were successfully scored
        conversations_closed = 0
        for detail in results["details"]:
            if detail.get("status") == "success":
                conversation_id = detail.get("conversation_id")
                if conversation_id:
                    try:
                        # Update conversation status to closed
                        close_response = supabase.table("conversations").update({
                            "status": "closed",
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        }).eq("id", conversation_id).execute()
                        
                        if close_response.data:
                            conversations_closed += 1
                            print(f"✅ Closed conversation {conversation_id} after successful lead scoring")
                        else:
                            print(f"⚠️  Failed to close conversation {conversation_id}")
                    except Exception as close_error:
                        print(f"❌ Error closing conversation {conversation_id}: {str(close_error)}")
        
        print(f"📊 Lead scoring summary: {results['successful']} scored, {conversations_closed} conversations closed")
        
        return AutoScoreLeadsResponse(
            status="success",
            message=f"Auto lead scoring completed for {len(stale_conversations)} conversations. {conversations_closed} conversations closed.",
            total_conversations_found=len(conversations_response.data),
            conversations_processed=results["total_processed"],
            successful_scores=results["successful"],
            failed_scores=results["failed"],
            skipped_scores=results["total_processed"] - results["successful"] - results["failed"],
            details=results["details"]
        )
        
    except Exception as e:
        print(f"Error in auto lead scoring for bot {bot_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to auto score leads: {str(e)}"
        )

# --- End Auto Lead Scoring Endpoint ---

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

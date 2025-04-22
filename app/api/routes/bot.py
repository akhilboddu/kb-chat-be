from fastapi import APIRouter, HTTPException, Body, Query
import datetime

from app.models.base import StatusResponse
from app.models.bot import (
    AddKnowledgeRequest,
)
from app.core import kb_manager, db_manager
from app.core.supabase_client import supabase

router = APIRouter(tags=["bots"])

@router.post("/bots/{bot_id}/knowledge", response_model=StatusResponse)
async def bot_knowledge_endpoint(bot_id: str, request: AddKnowledgeRequest):
    """
    Endpoint for adding verified knowledge to the bot's KB.
    """
    print(f"Received knowledge addition for bot_id: {bot_id}")
    
    if not request.knowledge_text or not request.knowledge_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Knowledge text cannot be empty"
        )
    
    try:
        # First, get the kb_id from the bot
        bot_response = supabase.table("bots").select("kb_id").eq("id", bot_id).execute()
        
        if not bot_response.data or len(bot_response.data) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Bot with ID {bot_id} not found"
            )
            
        kb_id = bot_response.data[0]["kb_id"]
            
        # Add to knowledge base with metadata
        success = kb_manager.add_to_kb(
            kb_id=kb_id,
            text_to_add=request.knowledge_text
        )
        
        if not success:
            print(f"kb_manager.add_to_kb returned False for KB {kb_id}")
            raise HTTPException(
                status_code=500,
                detail="Failed to add knowledge to the knowledge base (internal KB error)"
            )
        
        # Log the KB update
        log_success = db_manager.log_kb_update(kb_id, request.knowledge_text)
        if not log_success:
            # Log warning but don't fail the request
            print(f"Warning: Failed to log KB update for {kb_id}")

        # Update the knowledge sources table
        supabase.table("knowledge_sources").insert({
            "bot_id": bot_id,
            "source_type": "human conversation",
            "content": request.knowledge_text
        }).execute()
        
        return StatusResponse(
            status="success",
            message="Knowledge successfully added to the bot's knowledge base"
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
                detail=f"Failed to add knowledge to knowledge base: Metadata type error - {str(e)}"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to add knowledge to knowledge base: {str(e)}"
            )

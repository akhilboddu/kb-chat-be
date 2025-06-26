"""
Auto-Learning API Routes

Endpoints for analyzing conversations with handoffs to automatically
generate knowledge base improvements.
"""

from fastapi import APIRouter, HTTPException, Body, Query
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import logging
from uuid import UUID

from app.core.auto_learning import AutoLearningSystem, analyze_conversation_for_learning, batch_analyze_conversations
from app.core.learning_manager import learning_manager
from app.models.base import StatusResponse
from app.models.learning import Learning, ListLearningsResponse, UpdateLearningStatusRequest, BulkUpdateLearningsRequest

router = APIRouter(prefix="/auto-learning", tags=["auto-learning"])
logger = logging.getLogger(__name__)


# Request/Response Models
class AnalyzeConversationRequest(BaseModel):
    """Request model for analyzing a single conversation."""
    conversation_id: str = Field(..., description="The conversation ID to analyze")
    bot_id: UUID = Field(..., description="The bot ID that owns the conversation")


class BatchAnalyzeRequest(BaseModel):
    """Request model for batch analyzing multiple conversations."""
    conversation_ids: List[str] = Field(..., description="List of conversation IDs to analyze")
    bot_id: UUID = Field(..., description="The bot ID that owns the conversations")
    max_concurrent: Optional[int] = Field(5, description="Maximum concurrent analyses", le=10, ge=1)


class KBChunkResponse(BaseModel):
    """Response model for a generated KB chunk."""
    title: str
    content: str
    source: str
    source_type: str
    confidence_score: Optional[float] = None
    gap_summary: Optional[str] = None
    customer_question_theme: Optional[str] = None
    conversation_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


class AnalysisResponse(BaseModel):
    """Response model for conversation analysis."""
    success: bool
    conversation_id: str
    knowledge_gap_identified: bool
    kb_chunk: Optional[KBChunkResponse] = None
    gap_summary: Optional[str] = None
    confidence_score: Optional[float] = None
    message: str


class BatchAnalysisResponse(BaseModel):
    """Response model for batch analysis."""
    success: bool
    total_conversations: int
    successful_analyses: int
    kb_chunks_generated: int
    kb_chunks: List[KBChunkResponse] = []
    failed_conversations: List[str] = []
    message: str


# Endpoints
@router.post("/analyze-conversation", response_model=AnalysisResponse)
async def analyze_conversation(request: AnalyzeConversationRequest):
    """
    Analyze a single conversation that had a handoff to generate a KB chunk.
    
    This endpoint:
    1. Retrieves the conversation history
    2. Checks if it actually had a handoff
    3. Uses Gemini to analyze knowledge gaps
    4. Saves the learning to database if gap is identified
    5. Returns a ready-to-use KB chunk if a gap is identified
    """
    try:
        logger.info(f"Analyzing conversation {request.conversation_id} for auto-learning")
        
        # Analyze the conversation
        kb_chunk = await analyze_conversation_for_learning(request.conversation_id)
        
        if kb_chunk:
            # Save learning to database
            learning_data = {
                'bot_id': request.bot_id,
                'title': kb_chunk.get('title', 'Untitled Learning'),
                'content': kb_chunk.get('content', ''),
                'source': kb_chunk.get('source', f"Conversation {request.conversation_id}"),
                'confidence_score': kb_chunk.get('confidence_score'),
                'conversation_id': request.conversation_id,
                'gap_summary': kb_chunk.get('gap_summary'),
                'metadata': {
                    'source_type': kb_chunk.get('source_type', 'conversation'),
                    'customer_question_theme': kb_chunk.get('customer_question_theme'),
                    'analysis_timestamp': kb_chunk.get('analysis_timestamp')
                }
            }
            
            saved_learning = learning_manager.save_learning(learning_data)
            
            if saved_learning:
                logger.info(f"Saved learning {saved_learning.id} for bot {request.bot_id}")
            
            return AnalysisResponse(
                success=True,
                conversation_id=request.conversation_id,
                knowledge_gap_identified=True,
                kb_chunk=KBChunkResponse(**kb_chunk),
                gap_summary=kb_chunk.get('gap_summary'),
                confidence_score=kb_chunk.get('confidence_score'),
                message="Knowledge gap identified, KB chunk generated, and learning saved successfully"
            )
        else:
            return AnalysisResponse(
                success=True,
                conversation_id=request.conversation_id,
                knowledge_gap_identified=False,
                message="No actionable knowledge gap identified in this conversation"
            )
            
    except Exception as e:
        logger.error(f"Error analyzing conversation {request.conversation_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze conversation: {str(e)}"
        )


@router.post("/analyze-batch", response_model=BatchAnalysisResponse)
async def analyze_conversations_batch(request: BatchAnalyzeRequest):
    """
    Analyze multiple conversations in batch to generate KB chunks.
    
    This endpoint processes multiple conversations concurrently, saves learnings
    to the database, and returns all generated KB chunks along with summary statistics.
    """
    try:
        logger.info(f"Starting batch analysis of {len(request.conversation_ids)} conversations")
        
        # Analyze conversations in batch
        kb_chunks = await batch_analyze_conversations(request.conversation_ids)
        
        # Save learnings to database
        saved_learnings = []
        for chunk in kb_chunks:
            learning_data = {
                'bot_id': request.bot_id,
                'title': chunk.get('title', 'Untitled Learning'),
                'content': chunk.get('content', ''),
                'source': chunk.get('source', f"Batch Analysis"),
                'confidence_score': chunk.get('confidence_score'),
                'conversation_id': chunk.get('conversation_id'),
                'gap_summary': chunk.get('gap_summary'),
                'metadata': {
                    'source_type': chunk.get('source_type', 'conversation'),
                    'customer_question_theme': chunk.get('customer_question_theme'),
                    'batch_analysis': True,
                    'analysis_timestamp': chunk.get('analysis_timestamp')
                }
            }
            
            saved_learning = learning_manager.save_learning(learning_data)
            if saved_learning:
                saved_learnings.append(saved_learning)
        
        logger.info(f"Saved {len(saved_learnings)} learnings to database for bot {request.bot_id}")
        
        # Prepare response data
        kb_chunk_responses = [KBChunkResponse(**chunk) for chunk in kb_chunks]
        successful_analyses = len(kb_chunks)
        
        # Track failed conversations (those that didn't generate chunks)
        successful_conversation_ids = {chunk.get('conversation_id') for chunk in kb_chunks if chunk.get('conversation_id')}
        failed_conversations = [
            conv_id for conv_id in request.conversation_ids 
            if conv_id not in successful_conversation_ids
        ]
        
        return BatchAnalysisResponse(
            success=True,
            total_conversations=len(request.conversation_ids),
            successful_analyses=successful_analyses,
            kb_chunks_generated=len(kb_chunks),
            kb_chunks=kb_chunk_responses,
            failed_conversations=failed_conversations,
            message=f"Batch analysis complete: {len(kb_chunks)} KB chunks generated and {len(saved_learnings)} learnings saved from {len(request.conversation_ids)} conversations"
        )
        
    except Exception as e:
        logger.error(f"Error in batch analysis: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Batch analysis failed: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """
    Check if the auto-learning system is available and properly configured.
    """
    try:
        auto_learner = AutoLearningSystem()
        
        return {
            "status": "healthy",
            "gemini_available": auto_learner.gemini_available,
            "message": "Auto-learning system is ready" if auto_learner.gemini_available else "Auto-learning system disabled - Gemini not available"
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "gemini_available": False,
            "message": f"Auto-learning system error: {str(e)}"
        }


@router.get("/stats")
async def get_auto_learning_stats():
    """
    Get statistics about auto-learning usage and performance.
    This could be extended to track metrics from a database in the future.
    """
    # For now, return basic system status
    # In the future, this could query a metrics table to show:
    # - Number of conversations analyzed
    # - KB chunks generated
    # - Success rates
    # - Popular knowledge gap themes
    
    try:
        auto_learner = AutoLearningSystem()
        
        return {
            "system_status": "operational" if auto_learner.gemini_available else "limited",
            "gemini_available": auto_learner.gemini_available,
            "features": {
                "conversation_analysis": auto_learner.gemini_available,
                "kb_chunk_generation": auto_learner.gemini_available,
                "batch_processing": auto_learner.gemini_available
            },
            "message": "Auto-learning statistics - extend this endpoint to track usage metrics"
        }
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get auto-learning stats: {str(e)}"
        )


# Utility endpoint for testing
@router.post("/test-analysis")
async def test_analysis_capability():
    """
    Test endpoint to verify Gemini integration and analysis capability.
    Returns system status and capabilities.
    """
    try:
        auto_learner = AutoLearningSystem()
        
        if not auto_learner.gemini_available:
            raise HTTPException(
                status_code=503,
                detail="Auto-learning system unavailable - Gemini not configured"
            )
        
        return {
            "status": "ready",
            "gemini_model": "gemini-1.5-flash",
            "capabilities": [
                "Conversation analysis",
                "Knowledge gap identification", 
                "KB chunk generation",
                "Batch processing"
            ],
            "message": "Auto-learning system is fully operational"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test analysis failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"System test failed: {str(e)}"
        )


# Learning Management Endpoints
@router.get("/{bot_id}/learnings", response_model=ListLearningsResponse)
async def list_learnings(
    bot_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected"),
    page: int = Query(1, description="Page number", ge=1),
    page_size: int = Query(50, description="Items per page", ge=1, le=100)
):
    """
    List all learnings for a bot with optional filtering and pagination.
    """
    try:
        learnings, stats = learning_manager.list_learnings(
            bot_id=str(bot_id),
            status=status,
            page=page,
            page_size=page_size
        )
        
        return ListLearningsResponse(
            learnings=learnings,
            total_count=stats['total_count'],
            pending_count=stats['pending_count'],
            approved_count=stats['approved_count'],
            rejected_count=stats['rejected_count']
        )
        
    except Exception as e:
        logger.error(f"Error listing learnings for bot {bot_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list learnings: {str(e)}"
        )


@router.put("/learnings/{learning_id}/status", response_model=Learning)
async def update_learning_status(
    learning_id: UUID,
    request: UpdateLearningStatusRequest
):
    """
    Update the status of a specific learning.
    """
    try:
        success = learning_manager.update_learning_status(
            learning_id=str(learning_id),
            status=request.status
        )
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail="Learning not found or update failed"
            )
        
        # Get updated learning
        updated_learning = learning_manager.get_learning_by_id(str(learning_id))
        if not updated_learning:
            raise HTTPException(
                status_code=404,
                detail="Learning not found after update"
            )
        
        return updated_learning
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating learning {learning_id} status: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update learning status: {str(e)}"
        )


@router.put("/learnings/bulk-update", response_model=Dict[str, Any])
async def bulk_update_learnings(request: BulkUpdateLearningsRequest):
    """
    Bulk update the status of multiple learnings.
    """
    try:
        learning_ids = [str(learning_id) for learning_id in request.learning_ids]
        updated_count = learning_manager.bulk_update_status(
            learning_ids=learning_ids,
            status=request.status
        )
        
        return {
            "success": True,
            "updated_count": updated_count,
            "total_requested": len(request.learning_ids),
            "message": f"Successfully updated {updated_count}/{len(request.learning_ids)} learnings to status '{request.status}'"
        }
        
    except Exception as e:
        logger.error(f"Error in bulk update: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Bulk update failed: {str(e)}"
        )


@router.delete("/learnings/{learning_id}")
async def delete_learning(learning_id: UUID):
    """
    Delete a specific learning.
    """
    try:
        success = learning_manager.delete_learning(str(learning_id))
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail="Learning not found or deletion failed"
            )
        
        return {
            "success": True,
            "message": f"Learning {learning_id} deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting learning {learning_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete learning: {str(e)}"
        )


@router.get("/learnings/{learning_id}", response_model=Learning)
async def get_learning(learning_id: UUID):
    """
    Get a specific learning by ID.
    """
    try:
        learning = learning_manager.get_learning_by_id(str(learning_id))
        
        if not learning:
            raise HTTPException(
                status_code=404,
                detail="Learning not found"
            )
        
        return learning
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting learning {learning_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get learning: {str(e)}"
        ) 
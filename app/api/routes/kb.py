from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, List, Dict, Any
from app.core import kb_manager
from app.core.supabase_client import supabase
from app.core.contextualizer import contextualizer
from app.core.embeddings import embeddings_manager
import json

router = APIRouter(prefix="/bots/{bot_id}/kb", tags=["knowledge_base"])

@router.get("/sources")
async def list_kb_sources(bot_id: str):
    """List all knowledge sources with metadata"""
    # Get kb_id from bot
    bot_result = supabase.table("bots").select("kb_id").eq("id", bot_id).single().execute()
    if not bot_result.data:
        raise HTTPException(404, "Bot not found")
    
    kb_id = bot_result.data["kb_id"]
    
    # Query the view
    sources = supabase.table("vw_kb_sources")\
        .select("*")\
        .eq("kb_id", kb_id)\
        .order("last_updated", desc=True)\
        .execute()
    
    return {"sources": sources.data or []}

@router.get("/documents")
async def list_kb_documents(
    bot_id: str,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0)
):
    """List documents with filtering and search"""
    bot_result = supabase.table("bots").select("kb_id").eq("id", bot_id).single().execute()
    if not bot_result.data:
        raise HTTPException(404, "Bot not found")
    
    kb_id = bot_result.data["kb_id"]
    
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

@router.put("/documents/{document_id}")
async def update_document(
    bot_id: str, 
    document_id: str, 
    body: Dict[str, Any] = Body(...)
):
    """Edit a specific chunk and regenerate embeddings"""
    content = body.get("content")
    if not content:
        raise HTTPException(400, "Content is required")
    
    bot_result = supabase.table("bots").select("kb_id").eq("id", bot_id).single().execute()
    if not bot_result.data:
        raise HTTPException(404, "Bot not found")
    
    kb_id = bot_result.data["kb_id"]
    
    # Verify document exists and belongs to this KB
    doc_result = supabase.table("knowledge_base_documents")\
        .select("*")\
        .eq("kb_id", kb_id)\
        .eq("document_id", document_id)\
        .single()\
        .execute()
    
    if not doc_result.data:
        raise HTTPException(404, "Document not found")
    
    # Re-generate context and embedding
    context = contextualizer.create_context(content, content)
    ctx_text = f"{context} {content}"
    embedding = embeddings_manager.embed_query(ctx_text)
    
    if not embedding:
        raise HTTPException(500, "Failed to generate embedding")
    
    # Update document
    update_result = supabase.table("knowledge_base_documents")\
        .update({
            "content": content,
            "ctx_text": ctx_text,
            "embedding": embedding
        })\
        .eq("document_id", document_id)\
        .execute()
    
    return {"status": "updated", "document_id": document_id}

@router.delete("/documents/{document_id}")
async def delete_document(bot_id: str, document_id: str):
    """Delete a specific chunk"""
    bot_result = supabase.table("bots").select("kb_id").eq("id", bot_id).single().execute()
    if not bot_result.data:
        raise HTTPException(404, "Bot not found")
    
    kb_id = bot_result.data["kb_id"]
    
    result = supabase.table("knowledge_base_documents")\
        .delete()\
        .eq("kb_id", kb_id)\
        .eq("document_id", document_id)\
        .execute()
    
    if not result.data:
        raise HTTPException(404, "Document not found")
    
    return {"status": "deleted", "document_id": document_id}

@router.post("/cleanup-duplicates")
async def cleanup_duplicates(bot_id: str):
    """Remove duplicate chunks using existing KB manager method"""
    bot_result = supabase.table("bots").select("kb_id").eq("id", bot_id).single().execute()
    if not bot_result.data:
        raise HTTPException(404, "Bot not found")
    
    kb_id = bot_result.data["kb_id"]
    deleted_count = kb_manager.cleanup_duplicates(kb_id)
    
    return {"status": "success", "duplicates_removed": deleted_count}

@router.delete("/sources/{source_name}")
async def delete_source(bot_id: str, source_name: str):
    """Delete all chunks from a specific source"""
    bot_result = supabase.table("bots").select("kb_id").eq("id", bot_id).single().execute()
    if not bot_result.data:
        raise HTTPException(404, "Bot not found")
    
    kb_id = bot_result.data["kb_id"]
    
    result = supabase.table("knowledge_base_documents")\
        .delete()\
        .eq("kb_id", kb_id)\
        .eq("source_name", source_name)\
        .execute()
    
    return {
        "status": "deleted", 
        "source_name": source_name,
        "chunks_removed": len(result.data or [])
    } 
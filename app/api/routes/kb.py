from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, List, Dict, Any
from app.core import kb_manager
from app.core.supabase_client import supabase
from app.core.contextualizer import contextualizer
from app.core.embeddings import embeddings_manager
from app.core.config import llm
import json
import uuid
import hashlib
from datetime import datetime
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import asyncio
from uuid import uuid4
from celery.result import AsyncResult

router = APIRouter(prefix="/agents", tags=["knowledge_base"])

@router.get("/{agent_id}/sources")
async def list_kb_sources(agent_id: str):
    """List all knowledge sources with metadata"""
    # agent_id is the kb_id
    kb_id = agent_id
    
    # Query the view
    sources = supabase.table("vw_kb_sources")\
        .select("*")\
        .eq("kb_id", kb_id)\
        .order("last_updated", desc=True)\
        .execute()
    
    return {"sources": sources.data or []}

@router.get("/{agent_id}/documents")
async def list_kb_documents(
    agent_id: str,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0)
):
    """List documents with filtering and search"""
    kb_id = agent_id
    
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

@router.put("/{agent_id}/documents/{document_id}")
async def update_document(
    agent_id: str, 
    document_id: str, 
    body: Dict[str, Any] = Body(...)
):
    """Edit a specific chunk and regenerate embeddings"""
    content = body.get("content")
    if not content:
        raise HTTPException(400, "Content is required")
    
    kb_id = agent_id
    
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

@router.delete("/{agent_id}/documents/{document_id}")
async def delete_document(agent_id: str, document_id: str):
    """Delete a specific chunk"""
    kb_id = agent_id
    
    result = supabase.table("knowledge_base_documents")\
        .delete()\
        .eq("kb_id", kb_id)\
        .eq("document_id", document_id)\
        .execute()
    
    if not result.data:
        raise HTTPException(404, "Document not found")
    
    return {"status": "deleted", "document_id": document_id}

@router.post("/{agent_id}/cleanup-duplicates")
async def cleanup_duplicates(agent_id: str):
    """Remove duplicate chunks using existing KB manager method"""
    kb_id = agent_id
    deleted_count = kb_manager.cleanup_duplicates(kb_id)
    
    return {"status": "success", "duplicates_removed": deleted_count}

@router.delete("/{agent_id}/sources/{source_name}")
async def delete_source(agent_id: str, source_name: str):
    """Delete all chunks from a specific source"""
    kb_id = agent_id
    
    # Delete documents from knowledge_base_documents
    result = supabase.table("knowledge_base_documents")\
        .delete()\
        .eq("kb_id", kb_id)\
        .eq("source_name", source_name)\
        .execute()
    
    chunks_removed = len(result.data or [])
    
    # Also clean up the knowledge_sources table
    # First, find the bot_id from the kb_id
    try:
        bot_response = supabase.table("bots").select("id").eq("kb_id", kb_id).execute()
        if bot_response.data and len(bot_response.data) > 0:
            bot_id = bot_response.data[0]["id"]
            
            # Delete from knowledge_sources table
            # The knowledge_sources table stores source info differently, so we need to match by content pattern
            sources_response = supabase.table("knowledge_sources")\
                .select("*")\
                .eq("bot_id", bot_id)\
                .execute()
            
            if sources_response.data:
                for source in sources_response.data:
                    # Check if this source entry matches our deleted source
                    content = source.get("content", "")
                    if source_name in content:
                        supabase.table("knowledge_sources")\
                            .delete()\
                            .eq("id", source["id"])\
                            .execute()
                        print(f"Cleaned up knowledge_sources entry for {source_name}")
    except Exception as e:
        print(f"Warning: Failed to clean up knowledge_sources table: {str(e)}")
        # Don't fail the whole operation if knowledge_sources cleanup fails
    
    return {
        "status": "deleted", 
        "source_name": source_name,
        "chunks_removed": chunks_removed
    }

# NOTE: Internal heavy optimiser used by Celery – **do not expose as HTTP route**
async def _optimize_kb_internal(agent_id: str):
    try:
        # agent_id is the kb_id
        kb_id = agent_id
        
        # Get all documents in the KB
        all_docs = supabase.table("knowledge_base_documents")\
            .select("*")\
            .eq("kb_id", kb_id)\
            .execute()
        
        if not all_docs.data or len(all_docs.data) == 0:
            return {"status": "success", "message": "No documents to optimize", "stats": {}}
        
        documents = all_docs.data
        original_count = len(documents)
        
        # Initialize LLM for optimization
        if not llm:
            raise HTTPException(500, "LLM not configured")
        
        # Group documents by source for intelligent processing
        sources = {}
        for doc in documents:
            source_key = f"{doc['source_type']}:{doc.get('source_name', 'unknown')}"
            if source_key not in sources:
                sources[source_key] = []
            sources[source_key].append(doc)
        
        optimized_docs = []
        removed_count = 0
        merged_count = 0
        optimization_logs = []
        
        for source_key, source_docs in sources.items():
            if len(source_docs) <= 1:
                # Single document sources - just check for quality improvements
                optimized_docs.extend(source_docs)
                continue
            
            # Multi-document sources - apply AI optimization
            try:
                source_optimization = await optimize_source_documents(source_docs, llm, kb_id)
                optimized_docs.extend(source_optimization["optimized_docs"])
                merged_count += source_optimization["merged_count"]
                optimization_logs.append({
                    "source": source_key,
                    "original_count": len(source_docs),
                    "optimized_count": len(source_optimization["optimized_docs"]),
                    "summary": source_optimization["summary"]
                })
            except Exception as e:
                print(f"Error optimizing source {source_key}: {str(e)}")
                # If optimization fails, keep original documents
                optimized_docs.extend(source_docs)
                optimization_logs.append({
                    "source": source_key,
                    "error": str(e),
                    "status": "skipped"
                })
        
        # Remove all original documents
        delete_result = supabase.table("knowledge_base_documents")\
            .delete()\
            .eq("kb_id", kb_id)\
            .execute()
        
        # Insert optimized documents in batches
        if optimized_docs:
            insert_docs = []
            for doc in optimized_docs:
                # Prepare document for insertion (remove auto-generated fields)
                insert_doc = {k: v for k, v in doc.items() if k not in ['id']}
                # Ensure required fields are present
                if 'metadata' not in insert_doc:
                    insert_doc['metadata'] = {}
                if 'created_at' not in insert_doc:
                    insert_doc['created_at'] = datetime.utcnow().isoformat()
                insert_docs.append(insert_doc)
            
            # Insert in batches of 50 to avoid payload size limits
            batch_size = 50
            for i in range(0, len(insert_docs), batch_size):
                batch = insert_docs[i:i + batch_size]
                supabase.table("knowledge_base_documents").insert(batch).execute()
        
        # Calculate final statistics
        final_count = len(optimized_docs)
        removed_count = original_count - final_count
        
        optimization_stats = {
            "original_documents": original_count,
            "optimized_documents": final_count,
            "documents_removed": removed_count,
            "chunks_merged": merged_count,
            "sources_processed": len(sources),
            "compression_ratio": f"{((removed_count / original_count) * 100):.1f}%" if original_count > 0 else "0%",
            "optimization_logs": optimization_logs
        }
        
        return {
            "status": "success",
            "message": f"Knowledge base optimized successfully. Reduced {original_count} chunks to {final_count} optimized chunks.",
            "stats": optimization_stats
        }
        
    except Exception as e:
        print(f"Error in optimize_knowledge_base: {str(e)}")
        raise HTTPException(500, f"Optimization failed: {str(e)}")

async def optimize_source_documents(source_docs: List[Dict], llm_model, kb_id: str) -> Dict:
    """Optimize documents from a single source using AI"""
    
    try:
        print(f"Optimizing {len(source_docs)} documents for KB {kb_id}")
        
        # Step 1: Detect semantic similarities using embeddings
        embeddings = []
        for doc in source_docs:
            if doc.get('embedding'):
                # Handle different embedding formats
                embedding = doc['embedding']
                if isinstance(embedding, list):
                    # Already a list - use as is
                    embeddings.append(embedding)
                elif isinstance(embedding, str):
                    # Parse vector string format: [0.1, 0.2, ...]
                    try:
                        # Try parsing as JSON first
                        embedding = json.loads(embedding)
                        embeddings.append(embedding)
                    except (json.JSONDecodeError, ValueError):
                        # Fallback: manual parsing
                        embedding = embedding.replace('[', '').replace(']', '').split(',')
                        embedding = [float(x.strip()) for x in embedding if x.strip()]
                        embeddings.append(embedding)
                else:
                    # Unknown format - generate new embedding
                    ctx_text = doc.get('ctx_text') or doc.get('content', '')
                    embedding = embeddings_manager.embed_query(ctx_text)
                    embeddings.append(embedding or [0] * 1024)
            else:
                # Generate embedding if missing
                ctx_text = doc.get('ctx_text') or doc.get('content', '')
                embedding = embeddings_manager.embed_query(ctx_text)
                embeddings.append(embedding or [0] * 1024)
        
        # Step 2: Find similar document clusters
        similarity_threshold = 0.85  # High similarity threshold
        doc_clusters = []
        processed = set()
        
        for i, doc in enumerate(source_docs):
            if i in processed:
                continue
                
            cluster = [doc]
            cluster_indices = [i]
            
            for j, other_doc in enumerate(source_docs[i+1:], i+1):
                if j in processed:
                    continue
                    
                # Calculate cosine similarity
                similarity = cosine_similarity([embeddings[i]], [embeddings[j]])[0][0]
                
                if similarity > similarity_threshold:
                    cluster.append(other_doc)
                    cluster_indices.append(j)
                    processed.add(j)
            
            doc_clusters.append(cluster)
            processed.add(i)
        
        # Step 3: Apply AI optimization to clusters
        optimized_docs = []
        merged_count = 0
        
        for cluster in doc_clusters:
            if len(cluster) == 1:
                # Single document - keep as is but potentially improve quality
                optimized_docs.append(cluster[0])
            else:
                # Multiple similar documents - merge using AI
                try:
                    merged_doc = await merge_similar_documents(cluster, llm_model, kb_id)
                    optimized_docs.append(merged_doc)
                    merged_count += len(cluster) - 1
                except Exception as e:
                    print(f"Error merging documents: {str(e)}")
                    # If merging fails, keep the first document
                    optimized_docs.append(cluster[0])
        
        return {
            "optimized_docs": optimized_docs,
            "merged_count": merged_count,
            "summary": f"Processed {len(doc_clusters)} clusters, merged {merged_count} similar documents"
        }
    
    except Exception as e:
        print(f"Error in optimize_source_documents: {str(e)}")
        import traceback
        traceback.print_exc()
        # Return original documents if optimization fails
        return {
            "optimized_docs": source_docs,
            "merged_count": 0,
            "summary": f"Optimization failed: {str(e)}"
        }

async def merge_similar_documents(docs: List[Dict], llm_model, kb_id: str) -> Dict:
    """Merge similar documents using AI"""
    
    # Prepare content for AI analysis
    content_items = []
    for i, doc in enumerate(docs):
        content_items.append(f"CHUNK_{i}: {doc['content']}")
    
    combined_content = "\n\n".join(content_items)
    
    # AI prompt for merging similar content
    merge_prompt = f"""
You are an expert knowledge base optimizer. Your task is to merge the following similar text chunks into a single, comprehensive, and well-structured document.

MERGING GUIDELINES:
1. Combine all unique information from all chunks
2. Remove redundant or duplicate information
3. Maintain factual accuracy - never modify facts or data
4. Create a coherent, well-structured narrative
5. Preserve all important details and nuances
6. Ensure the merged content is self-contained and complete
7. Keep the merged content between 300-1200 characters for optimal retrieval

SIMILAR CHUNKS TO MERGE:

{combined_content}

Please provide the merged content in this exact JSON format:
{{
    "merged_content": "The merged and optimized content here...",
    "merge_summary": "Brief description of what was merged and optimized"
}}

IMPORTANT: Focus on creating one comprehensive chunk that captures all the essential information from the similar chunks while eliminating redundancy.
"""

    try:
        # Get AI optimization
        response = llm_model.invoke(merge_prompt)
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # Try to extract JSON from response
        import re
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            merge_result = json.loads(json_match.group())
            merged_content = merge_result.get("merged_content", "")
            
            if merged_content:
                # Create new optimized document based on the first document as template
                template_doc = docs[0]
                
                # Generate new context and embedding for merged content
                context = contextualizer.create_context(merged_content, merged_content)
                ctx_text = f"{context} {merged_content}"
                embedding = embeddings_manager.embed_query(ctx_text)
                
                # Create optimized document
                optimized_doc = {
                    "id": str(uuid.uuid4()),
                    "kb_id": kb_id,
                    "document_id": str(uuid.uuid4()),
                    "content": merged_content,
                    "ctx_text": ctx_text,
                    "embedding": embedding,
                    "source_type": template_doc["source_type"],
                    "source_name": template_doc.get("source_name"),
                    "source_url": template_doc.get("source_url"),
                    "metadata": {
                        "optimized": True,
                        "merged_from": len(docs),
                        "merge_summary": merge_result.get("merge_summary", ""),
                        "original_docs": [doc["document_id"] for doc in docs],
                        "optimization_date": datetime.utcnow().isoformat()
                    },
                    "created_at": datetime.utcnow().isoformat()
                }
                
                return optimized_doc
    
    except Exception as e:
        print(f"Error in AI merging: {str(e)}")
    
    # If AI merging fails, return the first document
    return docs[0]

# ---------------------------------------------------------------------------
# New asynchronous endpoint that merely enqueues the Celery job and returns a
# task identifier that the front-end can poll.  This prevents long-running
# optimisation from blocking the API worker.
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/optimize")
async def optimize_knowledge_base(agent_id: str, body: Dict[str, Any] = Body(None)):
    """Enqueue optimisation job and return task metadata."""

    similarity_threshold = body.get("similarity_threshold", 0.85) if body else 0.85

    # Create DB job row (if table exists)
    task_id = str(uuid4())
    try:
        supabase.table("kb_optimization_jobs").insert({
            "id": task_id,
            "kb_id": agent_id,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }).execute()
    except Exception as exc:
        # Table might not exist yet – continue without DB persistence
        print(f"Warning: could not insert optimisation job row: {exc}")

    # Send Celery task (import lazily to avoid circular import)
    from app.tasks.optimize import run_optimize_task  # noqa: WPS433
    run_optimize_task.apply_async(args=[agent_id], kwargs={"threshold": similarity_threshold}, task_id=task_id, routing_key="optimize")

    return {
        "status": "queued",
        "task_id": task_id,
        "message": "Optimisation started – polling status via /optimize/status/{task_id}"
    }

@router.get("/{agent_id}/optimize/status/{task_id}")
async def get_optimize_status(agent_id: str, task_id: str):
    """Return optimisation job status and, if completed, statistics."""
    try:
        row = supabase.table("kb_optimization_jobs").select("*").eq("id", task_id).single().execute()
        if row.data:
            return row.data
    except Exception:
        pass  # Table might not yet exist – fallback to Celery result backend

    result = AsyncResult(task_id)
    return {"status": result.status.lower(), "task_id": task_id} 
"""
Parallel processing pipeline for knowledge base operations.
Processes context generation, embeddings, and database operations concurrently
for maximum performance on multi-core systems.
"""

import os
import time
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing

# Import required components
from app.core.contextualizer import contextualizer
from app.core.embeddings import embeddings_manager
from app.core.supabase_client import supabase

# Import performance monitoring
try:
    from app.utils.performance_monitor import performance_monitor
    PERFORMANCE_MONITORING_AVAILABLE = True
except ImportError:
    PERFORMANCE_MONITORING_AVAILABLE = False

logger = logging.getLogger(__name__)


class ParallelKBProcessor:
    """
    Parallel processing pipeline for knowledge base operations.
    Processes context generation, embeddings, and database operations concurrently.
    """
    
    def __init__(self, max_workers: Optional[int] = None):
        """
        Initialize parallel processor.
        
        Args:
            max_workers: Maximum number of worker threads. Defaults to CPU count.
        """
        if max_workers is None:
            # Use CPU count but cap at 8 to avoid overwhelming the system
            max_workers = min(multiprocessing.cpu_count(), 8)
        
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        logger.info(f"Initialized ParallelKBProcessor with {max_workers} workers")
    
    async def process_chunks_parallel(
        self,
        chunks: List[str],
        full_document: str,
        kb_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        knowledge_source: str = "manual",
        source_name: Optional[str] = None,
        source_url: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Process chunks in parallel pipeline:
        Stage 1: Context generation (batches)
        Stage 2: Embeddings generation (batches) 
        Stage 3: Database preparation (async)
        
        Returns:
            Tuple of (processed_documents, success)
        """
        start_time = time.time()
        total_chunks = len(chunks)
        
        if not chunks:
            logger.warning("No chunks to process")
            return [], False
        
        logger.info(f"Starting parallel processing of {total_chunks} chunks")
        
        # Filter out empty chunks
        valid_chunks = [(i, chunk) for i, chunk in enumerate(chunks) if chunk.strip()]
        
        if not valid_chunks:
            logger.warning("All chunks were empty")
            return [], False
        
        # Get batch sizes from environment or use defaults
        context_batch_size = int(os.getenv("CONTEXT_BATCH_SIZE", "50"))
        embeddings_batch_size = int(os.getenv("EMBEDDINGS_BATCH_SIZE", "96"))
        
        try:
            # Stage 1: Parallel context generation
            logger.info(f"Stage 1: Generating contexts in batches of {context_batch_size}")
            contexts = await self._generate_contexts_parallel(
                full_document, 
                [chunk for _, chunk in valid_chunks],
                context_batch_size,
                progress_callback
            )
            
            # Stage 2: Parallel embeddings generation
            logger.info(f"Stage 2: Generating embeddings in batches of {embeddings_batch_size}")
            ctx_texts = [f"{context} {chunk}" for context, (_, chunk) in zip(contexts, valid_chunks)]
            embeddings = await self._generate_embeddings_parallel(
                ctx_texts,
                embeddings_batch_size,
                progress_callback
            )
            
            # Stage 3: Prepare documents for database insertion
            logger.info("Stage 3: Preparing documents for database")
            timestamp = int(time.time() * 1000)
            processed_documents = []
            
            for (original_idx, chunk), context, ctx_text, embedding in zip(valid_chunks, contexts, ctx_texts, embeddings):
                if embedding and any(abs(x) > 1e-10 for x in embedding):
                    # Merge metadata
                    doc_metadata = metadata.copy() if metadata else {}
                    doc_metadata['timestamp'] = timestamp
                    doc_metadata['chunk_index'] = original_idx
                    
                    document = {
                        'kb_id': kb_id,
                        'document_id': f"parallel_{timestamp}_{original_idx}",
                        'content': chunk,
                        'ctx_text': ctx_text,
                        'embedding': embedding,
                        'metadata': json.dumps(doc_metadata),
                        'knowledge_source': knowledge_source,
                        'source_type': knowledge_source,
                        'source_name': source_name or f"{knowledge_source}_{timestamp}",
                        'source_url': source_url
                    }
                    processed_documents.append(document)
            
            elapsed = time.time() - start_time
            logger.info(
                f"Parallel processing completed: {len(processed_documents)}/{total_chunks} documents "
                f"in {elapsed:.2f}s ({elapsed/total_chunks:.3f}s per chunk)"
            )
            
            # Record performance metrics
            if PERFORMANCE_MONITORING_AVAILABLE:
                performance_monitor.record_metric(
                    operation="parallel_kb_processing",
                    duration=elapsed,
                    status="success",
                    chunks_processed=len(processed_documents),
                    total_chunks=total_chunks,
                    per_chunk_time=elapsed/total_chunks if total_chunks > 0 else 0
                )
            
            # Update progress to 100% for this stage
            if progress_callback:
                progress_callback(100, f"Processed {len(processed_documents)} documents")
            
            return processed_documents, True
            
        except Exception as e:
            logger.error(f"Error in parallel processing: {e}")
            import traceback
            traceback.print_exc()
            
            # Record failure metrics
            if PERFORMANCE_MONITORING_AVAILABLE:
                elapsed = time.time() - start_time
                performance_monitor.record_metric(
                    operation="parallel_kb_processing",
                    duration=elapsed,
                    status="error",
                    error=str(e)
                )
            
            return [], False
    
    async def _generate_contexts_parallel(
        self, 
        full_document: str, 
        chunks: List[str], 
        batch_size: int,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """
        Generate contexts in parallel batches.
        """
        contexts = []
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        
        # Create batch tasks
        batch_futures = []
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            future = self.executor.submit(
                contextualizer.batch_create_contexts,
                full_document,
                batch,
                show_progress=False
            )
            batch_futures.append((i, future))
        
        # Process results as they complete
        completed = 0
        for i, future in batch_futures:
            try:
                batch_contexts = future.result(timeout=300)  # 5 min timeout
                contexts.extend(batch_contexts)
                completed += 1
                
                if progress_callback:
                    # Context generation is 0-30% of overall progress
                    percent = int((completed / total_batches) * 30)
                    progress_callback(percent, f"Generated contexts: batch {completed}/{total_batches}")
                    
            except Exception as e:
                logger.error(f"Error generating contexts for batch starting at {i}: {e}")
                # Use fallback contexts
                fallback_contexts = ["This section contains information from the document."] * len(chunks[i:i+batch_size])
                contexts.extend(fallback_contexts)
        
        return contexts
    
    async def _generate_embeddings_parallel(
        self,
        ctx_texts: List[str],
        batch_size: int,
        progress_callback: Optional[Callable] = None
    ) -> List[List[float]]:
        """
        Generate embeddings in parallel batches.
        """
        embeddings = []
        total_batches = (len(ctx_texts) + batch_size - 1) // batch_size
        
        # Create batch tasks
        batch_futures = []
        for i in range(0, len(ctx_texts), batch_size):
            batch = ctx_texts[i:i + batch_size]
            future = self.executor.submit(
                embeddings_manager.embed_texts,
                batch
            )
            batch_futures.append((i, future))
        
        # Process results as they complete
        completed = 0
        results_dict = {}  # Store results with their index to maintain order
        
        for i, future in batch_futures:
            try:
                batch_embeddings = future.result(timeout=300)  # 5 min timeout
                results_dict[i] = batch_embeddings
                completed += 1
                
                if progress_callback:
                    # Embeddings generation is 30-60% of overall progress
                    percent = 30 + int((completed / total_batches) * 30)
                    progress_callback(percent, f"Generated embeddings: batch {completed}/{total_batches}")
                    
            except Exception as e:
                logger.error(f"Error generating embeddings for batch starting at {i}: {e}")
                # Use zero embeddings as fallback
                embedding_dim = embeddings_manager.get_embedding_info().get("dimension", 1024)
                fallback_embeddings = [[0.0] * embedding_dim] * len(ctx_texts[i:i+batch_size])
                results_dict[i] = fallback_embeddings
        
        # Reconstruct embeddings in correct order
        for i in sorted(results_dict.keys()):
            embeddings.extend(results_dict[i])
        
        return embeddings
    
    def shutdown(self):
        """Shutdown the thread pool executor."""
        self.executor.shutdown(wait=True)
        logger.info("ParallelKBProcessor shutdown complete")


# Global instance
_parallel_processor = None

def get_parallel_processor(max_workers: Optional[int] = None) -> ParallelKBProcessor:
    """
    Get or create the singleton ParallelKBProcessor instance.
    
    Args:
        max_workers: Maximum number of worker threads
        
    Returns:
        ParallelKBProcessor instance
    """
    global _parallel_processor
    if _parallel_processor is None:
        _parallel_processor = ParallelKBProcessor(max_workers)
    return _parallel_processor
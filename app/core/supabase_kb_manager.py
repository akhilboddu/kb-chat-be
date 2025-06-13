"""
Supabase Vector DB Knowledge Base Manager
Implements Contextual RAG with Cohere embeddings and hybrid search
"""

import os
import json
import time
import hashlib
from typing import List, Optional, Dict, Any, Tuple
from uuid import uuid4

from app.core.supabase_client import supabase
from app.core.embeddings import embeddings_manager
from app.core.contextualizer import contextualizer
from app.core import data_processor


class KBManager:
    """
    Manages Knowledge Base collections in Supabase Vector DB for multiple tenants.
    Each tenant has a separate namespace identified by kb_id.
    Implements Contextual RAG with hybrid search (vector + BM25).
    """
    
    def __init__(self):
        self.supabase = supabase
        print("Initialized Supabase KB Manager with Contextual RAG")
    
    def create_or_get_kb(self, kb_id: str, name: Optional[str] = None, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a new knowledge base or gets an existing one.
        
        Args:
            kb_id: Unique identifier for the knowledge base
            name: Optional human-readable name for the KB
            agent_name: Optional agent name (for compatibility)
            
        Returns:
            Dictionary with kb_id and metadata
        """
        try:
            # Check if KB exists
            result = self.supabase.table('knowledge_bases').select('*').eq('kb_id', kb_id).execute()
            
            if result.data:
                print(f"Retrieved existing KB: {kb_id}")
                return {
                    'kb_id': kb_id,
                    'name': result.data[0].get('name'),
                    'agent_name': result.data[0].get('agent_name'),
                    'created_at': result.data[0].get('created_at')
                }
            else:
                # Create new KB
                kb_data = {
                    'kb_id': kb_id,
                    'name': name or kb_id,
                    'agent_name': agent_name
                }
                
                result = self.supabase.table('knowledge_bases').insert(kb_data).execute()
                print(f"Created new KB: {kb_id} with name: '{name}' and agent: '{agent_name}'")
                return kb_data
                
        except Exception as e:
            print(f"Error creating/getting KB {kb_id}: {e}")
            # Return a minimal structure to maintain compatibility
            return {'kb_id': kb_id, 'name': name or kb_id}
    
    def _generate_document_id(self, content: str, kb_id: str) -> str:
        """Generate a unique document ID based on content hash"""
        content_hash = hashlib.sha256(f"{kb_id}:{content}".encode()).hexdigest()[:16]
        return f"doc_{content_hash}"
    
    def populate_kb(self, kb_collection: Dict[str, Any], text_chunks: List[str], knowledge_source: str = "manual") -> None:
        """
        Populates a knowledge base with text chunks using Contextual RAG.
        
        Args:
            kb_collection: KB info dict (from create_or_get_kb)
            text_chunks: List of text chunks to add
            knowledge_source: Source of the knowledge (website, file, human conversation, manual)
        """
        kb_id = kb_collection['kb_id']
        
        # Filter out empty chunks
        valid_chunks = [chunk for chunk in text_chunks if chunk.strip()]
        
        if not valid_chunks:
            print(f"No valid chunks to add to KB {kb_id}")
            return
        
        # Join chunks to create full document context
        full_document = "\n\n".join(valid_chunks)
        
        # Process chunks in batches
        documents_to_insert = []
        
        for i, chunk in enumerate(valid_chunks):
            # Generate context for this chunk
            context = contextualizer.create_context(full_document, chunk)
            ctx_text = f"{context} {chunk}"
            
            # Generate embedding for the contextualized text
            embedding = embeddings_manager.embed_query(ctx_text)
            
            if embedding:
                document_data = {
                    'kb_id': kb_id,
                    'document_id': self._generate_document_id(chunk, kb_id),
                    'content': chunk,
                    'ctx_text': ctx_text,
                    'embedding': embedding,
                    'metadata': json.dumps({'chunk_index': i}),
                    'knowledge_source': knowledge_source
                }
                documents_to_insert.append(document_data)
        
        # Batch insert documents
        if documents_to_insert:
            try:
                # Insert in batches of 100 to avoid size limits
                batch_size = 100
                for i in range(0, len(documents_to_insert), batch_size):
                    batch = documents_to_insert[i:i + batch_size]
                    self.supabase.table('knowledge_base_documents').insert(batch).execute()
                
                print(f"Added {len(documents_to_insert)} contextualized chunks to KB {kb_id} from source: {knowledge_source}")
            except Exception as e:
                print(f"Error inserting documents to KB {kb_id}: {e}")
    
    def add_to_kb(self, kb_id: str, text_to_add: str, metadata: Optional[Dict[str, Any]] = None, knowledge_source: str = "manual") -> bool:
        """
        Adds text to a knowledge base with contextualization and optional metadata.
        
        Args:
            kb_id: ID of the knowledge base to update
            text_to_add: Text content to add
            metadata: Optional metadata dictionary
            knowledge_source: Source of the knowledge (website, file, human conversation, manual)
            
        Returns:
            Success status
        """
        if not text_to_add or not text_to_add.strip():
            print(f"No valid content to add to KB {kb_id}")
            return False
        
        # Get the KB to ensure it exists
        kb_collection = self.create_or_get_kb(kb_id)
        
        # Process and chunk the text
        chunks = data_processor.chunk_text(text_to_add)
        if not chunks:
            print(f"Text resulted in no chunks, nothing to add to KB {kb_id}")
            return False
        
        # Generate unique timestamp for this batch
        timestamp = int(time.time() * 1000)
        
        # For context generation, use the full text as document
        full_document = text_to_add
        
        documents_to_insert = []
        
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            
            # Generate context
            context = contextualizer.create_context(full_document, chunk)
            ctx_text = f"{context} {chunk}"
            
            # Generate embedding
            embedding = embeddings_manager.embed_query(ctx_text)
            
            if embedding:
                # Merge metadata with timestamp
                doc_metadata = metadata.copy() if metadata else {}
                doc_metadata['timestamp'] = timestamp
                doc_metadata['chunk_index'] = i
                
                document_data = {
                    'kb_id': kb_id,
                    'document_id': f"add_{timestamp}_{i}",
                    'content': chunk,
                    'ctx_text': ctx_text,
                    'embedding': embedding,
                    'metadata': json.dumps(doc_metadata),
                    'knowledge_source': knowledge_source
                }
                documents_to_insert.append(document_data)
        
        if documents_to_insert:
            try:
                # Batch insert
                batch_size = 100
                for i in range(0, len(documents_to_insert), batch_size):
                    batch = documents_to_insert[i:i + batch_size]
                    self.supabase.table('knowledge_base_documents').insert(batch).execute()
                
                print(f"Added {len(documents_to_insert)} new contextualized chunks to KB {kb_id} from source: {knowledge_source}")
                return True
            except Exception as e:
                print(f"Error adding documents to KB {kb_id}: {e}")
                return False
        else:
            print(f"No valid documents generated from text, nothing added to KB {kb_id}")
            return False
    
    def get_similar_docs(self, kb_id: str, query: str, n_results: int = 5) -> List[dict]:
        """
        Retrieves similar documents using hybrid search (vector + BM25).
        
        Args:
            kb_id: ID of the knowledge base to query
            query: Query text
            n_results: Number of results to return
            
        Returns:
            List of dictionaries with 'document' and 'distance' keys
        """
        try:
            # Embed the query
            query_embedding = embeddings_manager.embed_query(query)
            
            if not query_embedding:
                print(f"Failed to embed query for KB {kb_id}")
                return []
            
            # Call hybrid search RPC
            result = self.supabase.rpc('hybrid_search', {
                'kb_id_param': kb_id,
                'query_text': query,
                'query_embedding': query_embedding,
                'match_count': n_results
            }).execute()
            
            if not result.data:
                print(f"No documents found for query in KB {kb_id}")
                return []
            
            # Format results for backward compatibility
            doc_info = []
            for doc in result.data:
                # Convert score to distance (1 - score for backward compatibility)
                distance = 1.0 - doc['score']
                doc_info.append({
                    'document': doc['content'],
                    'distance': distance
                })
            
            print("_______________________________________________")
            print(f"[KB RESULT] Returned {len(doc_info)} docs via hybrid search")
            print("_______________________________________________")
            
            return doc_info
            
        except Exception as e:
            print(f"Error querying KB {kb_id}: {e}")
            return []
    
    def list_kbs(self) -> List[Dict[str, Optional[str]]]:
        """
        Lists all existing knowledge bases with their metadata and summaries.
        
        Returns:
            List of dicts with 'kb_id', 'name', and 'summary'
        """
        kb_info_list = []
        max_summary_length = 150
        
        try:
            # Get all KBs
            kbs_result = self.supabase.table('knowledge_bases').select('*').execute()
            
            for kb in kbs_result.data:
                kb_id = kb['kb_id']
                summary = "(KB is empty or inaccessible)"
                
                try:
                    # Get first document for summary
                    doc_result = (self.supabase.table('knowledge_base_documents')
                        .select('content')
                        .eq('kb_id', kb_id)
                        .limit(1)
                        .execute())
                    
                    if doc_result.data:
                        first_doc = doc_result.data[0]['content']
                        # Truncate if necessary
                        if len(first_doc) > max_summary_length:
                            summary = first_doc[:max_summary_length] + "..."
                        else:
                            summary = first_doc
                    else:
                        # Check if KB is empty
                        count_result = (self.supabase.table('knowledge_base_documents')
                            .select('id', count='exact')
                            .eq('kb_id', kb_id)
                            .execute())
                        
                        if count_result.count == 0:
                            summary = "(KB is empty)"
                            
                except Exception as e:
                    print(f"Error getting summary for KB {kb_id}: {e}")
                    summary = "(Error retrieving summary)"
                
                kb_info_list.append({
                    'kb_id': kb_id,
                    'name': kb.get('name') or kb.get('agent_name'),
                    'summary': summary
                })
            
            print(f"Found {len(kb_info_list)} existing KBs.")
            return kb_info_list
            
        except Exception as e:
            print(f"Error listing KBs: {e}")
            return []
    
    def delete_kb(self, kb_id: str) -> bool:
        """
        Deletes a knowledge base and all its documents.
        
        Args:
            kb_id: Unique identifier for the knowledge base to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            # Delete KB (cascade will delete documents)
            result = (self.supabase.table('knowledge_bases')
                .delete()
                .eq('kb_id', kb_id)
                .execute())
            
            if result.data:
                print(f"Successfully deleted KB: {kb_id}")
                return True
            else:
                print(f"KB {kb_id} not found, nothing to delete.")
                return True  # Consider success as end state achieved
                
        except Exception as e:
            print(f"Error deleting KB {kb_id}: {e}")
            return False
    
    def get_kb_content(self, kb_id: str, limit: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves documents and metadata from a knowledge base with pagination.
        
        Args:
            kb_id: ID of the knowledge base to query
            limit: Maximum number of documents to return
            offset: Starting offset for pagination
            
        Returns:
            Dictionary with documents, ids, total_count, limit, and offset
        """
        try:
            # Build query
            query = (self.supabase.table('knowledge_base_documents')
                .select('id, document_id, content', count='exact')
                .eq('kb_id', kb_id)
                .order('created_at'))
            
            # Apply pagination
            if offset is not None:
                query = query.range(offset, offset + (limit or 1000) - 1)
            elif limit is not None:
                query = query.limit(limit)
            
            result = query.execute()
            
            # Extract documents and IDs
            documents = [doc['content'] for doc in result.data]
            ids = [doc['document_id'] for doc in result.data]
            
            return {
                'documents': documents,
                'ids': ids,
                'total_count': result.count or 0,
                'limit': limit,
                'offset': offset
            }
            
        except Exception as e:
            print(f"Error retrieving content from KB {kb_id}: {e}")
            raise e
    
    def cleanup_duplicates(self, kb_id: str) -> int:
        """
        Finds and removes duplicate documents based on content hash.
        
        Args:
            kb_id: The unique identifier for the knowledge base
            
        Returns:
            The number of duplicate documents deleted
        """
        print(f"Starting duplicate cleanup for KB: {kb_id}")
        deleted_count = 0
        
        try:
            # Get all documents
            result = (self.supabase.table('knowledge_base_documents')
                .select('id, content')
                .eq('kb_id', kb_id)
                .execute())
            
            if not result.data:
                print(f"KB {kb_id} is empty or could not retrieve documents.")
                return 0
            
            # Find duplicates based on normalized content
            seen_content = {}  # content_hash: first_id
            ids_to_delete = []
            
            for doc in result.data:
                # Normalize content
                normalized = " ".join(doc['content'].split())
                content_hash = hashlib.sha256(normalized.encode()).hexdigest()
                
                if content_hash in seen_content:
                    # Found duplicate
                    ids_to_delete.append(doc['id'])
                else:
                    seen_content[content_hash] = doc['id']
            
            if ids_to_delete:
                print(f"Found {len(ids_to_delete)} duplicate documents to delete in KB: {kb_id}")
                
                # Delete in batches
                batch_size = 100
                for i in range(0, len(ids_to_delete), batch_size):
                    batch = ids_to_delete[i:i + batch_size]
                    (self.supabase.table('knowledge_base_documents')
                        .delete()
                        .in_('id', batch)
                        .execute())
                
                deleted_count = len(ids_to_delete)
                print(f"Successfully deleted {deleted_count} duplicates from KB: {kb_id}")
            else:
                print(f"No duplicate documents found in KB: {kb_id}")
            
            return deleted_count
            
        except Exception as e:
            print(f"Error during cleanup for KB {kb_id}: {e}")
            raise e


# Singleton instance
kb_manager = KBManager() 
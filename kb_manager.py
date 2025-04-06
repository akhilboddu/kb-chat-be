import os
import chromadb
from chromadb.errors import NotFoundError
from chromadb.config import Settings
from typing import List, Optional, Dict, Any
from chromadb.api.models.Collection import Collection
from config import CHROMADB_PATH, chroma_embedding_function
import data_processor
import time

class KBManager:
    """
    Manages Knowledge Base collections in ChromaDB for multiple tenants.
    Each tenant has a separate collection identified by kb_id.
    """
    
    def __init__(self):
        # Initialize ChromaDB client
        os.makedirs(CHROMADB_PATH, exist_ok=True)  # Ensure the directory exists
        self.client = chromadb.PersistentClient(path=CHROMADB_PATH)
        print(f"Initialized ChromaDB client with path: {CHROMADB_PATH}")
    
    def create_or_get_kb(self, kb_id: str, name: Optional[str] = None) -> Collection:
        """
        Creates a new knowledge base collection or gets an existing one.
        If creating, optionally stores the provided name in the collection metadata.
        
        Args:
            kb_id: Unique identifier for the knowledge base
            name: Optional human-readable name for the agent/KB.
            
        Returns:
            ChromaDB collection
        """
        try:
            # Try to get existing collection
            collection = self.client.get_collection(
                name=kb_id,
                embedding_function=chroma_embedding_function
            )
            print(f"Retrieved existing collection: {kb_id}")
            # Note: We don't update the name if the collection already exists via this method.
            # A separate update method would be needed if name changes are required.
            return collection
        except NotFoundError:  # Catch the specific ChromaDB error
            # Prepare metadata
            collection_metadata = {"hnsw:space": "cosine"}
            if name:
                collection_metadata["agent_name"] = name
                print(f"Creating new collection: {kb_id} with name: '{name}' using cosine distance.")
            else:
                 print(f"Creating new collection: {kb_id} (no name provided) using cosine distance.")

            # Create new collection with metadata
            collection = self.client.create_collection(
                name=kb_id,
                embedding_function=chroma_embedding_function,
                metadata=collection_metadata
            )
            return collection
    
    def populate_kb(self, kb_collection: Collection, text_chunks: List[str]) -> None:
        """
        Populates a knowledge base collection with text chunks using simple indexed IDs.
        Best used for initial population.
        
        Args:
            kb_collection: ChromaDB collection
            text_chunks: List of text chunks to add
        """
        documents = []
        ids = []
        
        for i, chunk in enumerate(text_chunks):
            if not chunk.strip():  # Skip empty chunks
                continue
            documents.append(chunk)
            ids.append(f"chunk_{i}") # Simple IDs for initial load
        
        if documents:  # Only add if there are non-empty documents
            kb_collection.add(
                documents=documents,
                ids=ids
            )
            print(f"Added {len(documents)} chunks to collection {kb_collection.name} (Initial population)")
    
    def add_to_kb(self, kb_id: str, text_to_add: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Adds text update(s) to a knowledge base collection with unique IDs and optional metadata.
        
        Args:
            kb_id: ID of the knowledge base to update
            text_to_add: Text content to add
            metadata: Optional dictionary of metadata to associate with the added documents.
            
        Returns:
            Success status
        """
        if not text_to_add or not text_to_add.strip():
            print(f"No valid content to add to KB {kb_id}")
            return False
            
        # Get the KB collection
        collection = self.create_or_get_kb(kb_id)
        
        # Process and chunk the text
        chunks = data_processor.chunk_text(text_to_add)
        if not chunks:
             print(f"Text resulted in no chunks, nothing to add to KB {kb_id}")
             return False
        
        # Generate unique IDs for these new chunks
        documents_to_add = []
        ids_to_add = []
        metadatas_to_add = [] # List to hold metadata for each chunk
        timestamp = int(time.time() * 1000) # Milliseconds for better uniqueness
        for i, chunk in enumerate(chunks):
             if not chunk.strip():
                 continue
             documents_to_add.append(chunk)
             ids_to_add.append(f"add_{timestamp}_{i}") # Unique ID based on time
             # Add the provided metadata (or None) for each chunk
             metadatas_to_add.append(metadata)

        if documents_to_add:
            collection.add(
                documents=documents_to_add,
                ids=ids_to_add,
                metadatas=metadatas_to_add # Pass the list of metadata dictionaries
            )
            print(f"Added {len(documents_to_add)} new unique chunks to collection {collection.name}")
            return True
        else:
            print(f"No valid documents generated from text, nothing added to KB {kb_id}")
            return False
    
    def get_similar_docs(self, kb_id: str, query: str, n_results: int = 5) -> List[dict]:
        """
        Retrieves similar documents and their distances from a knowledge base collection.
        
        Args:
            kb_id: ID of the knowledge base to query
            query: Query text
            n_results: Number of results to return
            
        Returns:
            List of dictionaries, each containing 'document' (str) and 'distance' (float).
            Returns an empty list if no documents are found or an error occurs.
        """
        try:
            collection = self.create_or_get_kb(kb_id)
            
            # Query the collection, including distances
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                include=['documents', 'distances'] # Explicitly include distances
            )
            
            # Extract and format the results
            if (
                results 
                and results.get('documents') 
                and results.get('distances') 
                and results['documents'][0] is not None # Check list is not empty
                and results['distances'][0] is not None
            ):
                docs = results['documents'][0]
                distances = results['distances'][0]
                
                # Combine documents and distances
                doc_info = [
                    {"document": doc, "distance": dist} 
                    for doc, dist in zip(docs, distances)
                ]
                return doc_info
            else:
                print(f"No documents or distances found for query in KB {kb_id}")
                return []
        except Exception as e:
            print(f"Error querying KB {kb_id}: {e}")
            return []

    def list_kbs(self) -> List[Dict[str, Optional[str]]]:
        """
        Lists all existing knowledge base collections along with their name (if set)
        and a preview/summary derived from the first document.

        Returns:
            A list of dictionaries, where each dictionary contains 
            'kb_id' (str), 'name' (Optional[str]), and 'summary' (str).
        """
        kb_info_list = []
        max_summary_length = 150 # Limit the summary length
        try:
            collections = self.client.list_collections()
            for collection in collections:
                summary = "(KB is empty or inaccessible)" # Default summary
                agent_name = collection.metadata.get("agent_name") if collection.metadata else None
                
                try:
                    # Get the first document to use as a summary
                    results = collection.get(limit=1, include=['documents'])
                    if results and results['documents'] and results['documents'][0]:
                        first_doc = results['documents'][0]
                        # Truncate if necessary
                        if len(first_doc) > max_summary_length:
                            summary = first_doc[:max_summary_length] + "..."
                        else:
                            summary = first_doc
                    elif collection.count() == 0:
                         summary = "(KB is empty)"
                         
                except Exception as get_error:
                    print(f"Error getting summary for collection {collection.name}: {get_error}")
                    summary = "(Error retrieving summary)"

                kb_info_list.append({
                    "kb_id": collection.name,
                    "name": agent_name,
                    "summary": summary
                })
                
            print(f"Found {len(kb_info_list)} existing KBs.")
            return kb_info_list
        except Exception as e:
            print(f"Error listing collections: {e}")
            return [] # Return empty list on error

    def delete_kb(self, kb_id: str) -> bool:
        """
        Deletes a knowledge base collection.

        Args:
            kb_id: Unique identifier for the knowledge base to delete.

        Returns:
            True if deletion was successful or collection didn't exist, False otherwise.
        """
        try:
            self.client.delete_collection(name=kb_id)
            print(f"Successfully deleted collection: {kb_id}")
            return True
        except NotFoundError:
            print(f"Collection {kb_id} not found, nothing to delete.")
            return True # Considered success as the end state is achieved
        except Exception as e:
            print(f"Error deleting collection {kb_id}: {e}")
            return False

    def get_kb_content(self, kb_id: str, limit: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves documents, IDs, and total count from a knowledge base collection,
        with optional pagination.

        Args:
            kb_id: ID of the knowledge base to query.
            limit: Optional maximum number of documents to return.
            offset: Optional starting offset for retrieving documents.

        Returns:
            A dictionary containing:
                - 'documents': List of document strings.
                - 'ids': List of corresponding document IDs.
                - 'total_count': Total number of documents in the collection.
                - 'limit': The limit used.
                - 'offset': The offset used.
            Returns an empty dictionary structure with total_count 0 if KB not found.
        
        Raises:
            Exception: If there is an unexpected error retrieving the collection content.
        """
        try:
            collection = self.client.get_collection(name=kb_id) # Get collection first
            total_count = collection.count()
            
            # Prepare arguments for get(), filtering out None values
            get_args = {
                'include': ['documents'] # Only fetch docs. IDs are returned by default.
            }
            if limit is not None:
                get_args['limit'] = limit
            if offset is not None:
                get_args['offset'] = offset

            results = collection.get(**get_args)
            
            return {
                "documents": results.get('documents', []),
                "ids": results.get('ids', []),
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            }

        except NotFoundError:
            print(f"Collection {kb_id} not found when trying to get content.")
            # Return structure indicating not found but not an error state
            return {
                "documents": [],
                "ids": [],
                "total_count": 0,
                "limit": limit,
                "offset": offset
            }
        except Exception as e:
            print(f"Error retrieving content from KB {kb_id}: {e}")
            # Raise the exception to be handled by the API layer
            raise e 

# Singleton instance
kb_manager = KBManager()

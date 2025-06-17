"""
Cohere Embeddings Wrapper for Supabase Vector Store
Handles batch processing and error handling for Cohere's embed-english-v3.0 model
"""

import os
import time
import logging
from typing import List, Optional, Dict, Any
import cohere
from cohere.errors import TooManyRequestsError, BadRequestError
from dotenv import load_dotenv

# Import performance monitoring
try:
    from app.utils.performance_monitor import performance_monitor
    PERFORMANCE_MONITORING_AVAILABLE = True
except ImportError:
    PERFORMANCE_MONITORING_AVAILABLE = False

# Load environment variables at module import time
load_dotenv()

logger = logging.getLogger(__name__)


class CohereEmbeddings:
    """
    Wrapper for Cohere embeddings API with batch processing support.
    Uses embed-english-v3.0 model which produces 1024-dimensional vectors.
    """
    
    BATCH_SIZE = 96  # Cohere's max texts per request
    MODEL = "embed-english-v3.0"
    EMBEDDING_DIM = 1024
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Cohere client.
        
        Args:
            api_key: Cohere API key. If not provided, uses COHERE_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("COHERE_API_KEY")
        if not self.api_key:
            raise ValueError("COHERE_API_KEY environment variable not set")
        
        self.client = cohere.Client(api_key=self.api_key)
        logger.info(f"Initialized Cohere embeddings with model: {self.MODEL}")
    
    def embed_texts(
        self, 
        texts: List[str], 
        input_type: str = "search_document",
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> List[List[float]]:
        """
        Generate embeddings for a list of texts with automatic batching.
        
        Args:
            texts: List of texts to embed
            input_type: One of "search_document", "search_query", "classification", "clustering"
            max_retries: Maximum number of retry attempts for rate limits
            retry_delay: Initial delay between retries (exponential backoff)
            
        Returns:
            List of embedding vectors (each is 1024 dimensions)
        """
        if not texts:
            return []
        
        # Performance monitoring start
        start_time = time.time()
        success = True
        error_msg = None
        
        try:
            # Remove empty texts and track their indices
            non_empty_texts = []
            non_empty_indices = []
            for i, text in enumerate(texts):
                if text and text.strip():
                    non_empty_texts.append(text)
                    non_empty_indices.append(i)
        
            if not non_empty_texts:
                logger.warning("All texts were empty, returning empty embeddings")
                return [[0.0] * self.EMBEDDING_DIM for _ in texts]
            
            all_embeddings = []
            
            # Process in batches
            for i in range(0, len(non_empty_texts), self.BATCH_SIZE):
                batch = non_empty_texts[i:i + self.BATCH_SIZE]
                batch_embeddings = self._embed_batch_with_retry(
                    batch, 
                    input_type, 
                    max_retries, 
                    retry_delay
                )
                all_embeddings.extend(batch_embeddings)
            
            # Reconstruct full embedding list with zeros for empty texts
            full_embeddings = []
            embedding_idx = 0
            for i in range(len(texts)):
                if i in non_empty_indices:
                    full_embeddings.append(all_embeddings[embedding_idx])
                    embedding_idx += 1
                else:
                    # Empty text gets zero vector
                    full_embeddings.append([0.0] * self.EMBEDDING_DIM)
        
        except Exception as e:
            success = False
            error_msg = str(e)
            logger.error(f"Error in embed_texts: {e}")
            raise
        finally:
            # Performance monitoring end
            try:
                elapsed_time = time.time() - start_time
                if PERFORMANCE_MONITORING_AVAILABLE:
                    performance_monitor.record_embeddings_performance(
                        provider="cohere",
                        model=self.MODEL,
                        batch_size=len(texts),
                        duration=elapsed_time,
                        success=success,
                        error=error_msg
                    )
            except Exception as e:
                logger.warning(f"Failed to record embeddings performance: {e}")
        
        return full_embeddings
    
    def embed_query(self, query: str) -> List[float]:
        """
        Generate embedding for a search query.
        
        Args:
            query: Search query text
            
        Returns:
            1024-dimensional embedding vector
        """
        if not query or not query.strip():
            return [0.0] * self.EMBEDDING_DIM
        
        embeddings = self.embed_texts([query], input_type="search_query")
        return embeddings[0]
    
    def _embed_batch_with_retry(
        self, 
        batch: List[str], 
        input_type: str,
        max_retries: int,
        retry_delay: float
    ) -> List[List[float]]:
        """
        Embed a single batch with retry logic for rate limits.
        
        Args:
            batch: List of texts (max 96)
            input_type: Cohere input type
            max_retries: Maximum retry attempts
            retry_delay: Initial retry delay
            
        Returns:
            List of embeddings for the batch
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = self.client.embed(
                    texts=batch,
                    model=self.MODEL,
                    input_type=input_type
                )
                
                # Extract embeddings from response
                embeddings = []
                for embedding in response.embeddings:
                    if isinstance(embedding, list):
                        embeddings.append(embedding)
                    else:
                        # Handle different response formats
                        embeddings.append(embedding.float_)
                
                logger.debug(f"Successfully embedded batch of {len(batch)} texts")
                return embeddings
                
            except TooManyRequestsError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Rate limit hit, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Max retries exceeded for batch embedding: {e}")
                    
            except BadRequestError as e:
                logger.error(f"Bad request error (likely text too long): {e}")
                # For bad requests, truncate texts and retry
                truncated_batch = [text[:8000] for text in batch]  # Cohere's approximate limit
                try:
                    response = self.client.embed(
                        texts=truncated_batch,
                        model=self.MODEL,
                        input_type=input_type
                    )
                    embeddings = []
                    for embedding in response.embeddings:
                        if isinstance(embedding, list):
                            embeddings.append(embedding)
                        else:
                            embeddings.append(embedding.float_)
                    logger.warning(f"Successfully embedded batch after truncation")
                    return embeddings
                except Exception as e2:
                    logger.error(f"Failed even after truncation: {e2}")
                    last_error = e2
                    
            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error embedding batch: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        
        # If all retries failed, raise the last error
        raise last_error or Exception("Failed to embed batch after all retries")
    
    def get_embedding_info(self) -> Dict[str, Any]:
        """
        Get information about the embedding model.
        
        Returns:
            Dictionary with model info
        """
        return {
            "model": self.MODEL,
            "dimension": self.EMBEDDING_DIM,
            "batch_size": self.BATCH_SIZE,
            "provider": "cohere"
        }


# Singleton instance for convenience
_embeddings_instance = None

def get_embeddings() -> CohereEmbeddings:
    """
    Get or create the singleton CohereEmbeddings instance.
    
    Returns:
        CohereEmbeddings instance
    """
    global _embeddings_instance
    if _embeddings_instance is None:
        _embeddings_instance = CohereEmbeddings()
    return _embeddings_instance

# Create singleton instance for import
embeddings_manager = get_embeddings()

# Add backward compatibility check for flexible embeddings
try:
    from app.core.embeddings_flexible import get_embeddings as get_flexible_embeddings
    
    # Check if user wants to use flexible embeddings
    import os
    if os.getenv("USE_FLEXIBLE_EMBEDDINGS", "false").lower() == "true":
        print("Using flexible embeddings system")
        embeddings_manager = get_flexible_embeddings()
    else:
        print("Using Cohere embeddings (legacy)")
except ImportError:
    print("Flexible embeddings not available, using Cohere embeddings") 
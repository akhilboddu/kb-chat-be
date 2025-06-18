"""
Flexible Embeddings Wrapper supporting multiple providers
Allows switching between Cohere and HuggingFace embeddings via environment variables
"""

import os
import logging
import threading
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class BaseEmbeddings(ABC):
    """Abstract base class for embeddings providers"""
    
    @abstractmethod
    def embed_texts(self, texts: List[str], **kwargs) -> List[List[float]]:
        """Generate embeddings for a list of texts"""
        pass
    
    @abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a search query"""
        pass
    
    @abstractmethod
    def get_embedding_info(self) -> Dict[str, Any]:
        """Get information about the embedding model"""
        pass


class CohereEmbeddings(BaseEmbeddings):
    """Cohere embeddings implementation (wrapper around existing implementation)"""
    
    def __init__(self, api_key: Optional[str] = None):
        # Import the existing Cohere implementation
        from app.core.embeddings import CohereEmbeddings as CohereImpl
        self.impl = CohereImpl(api_key)
    
    def embed_texts(self, texts: List[str], **kwargs) -> List[List[float]]:
        return self.impl.embed_texts(texts, **kwargs)
    
    def embed_query(self, query: str) -> List[float]:
        return self.impl.embed_query(query)
    
    def get_embedding_info(self) -> Dict[str, Any]:
        return self.impl.get_embedding_info()


class HuggingFaceEmbeddings(BaseEmbeddings):
    """HuggingFace embeddings implementation with worker-safe model loading"""
    
    # Default to the best open-source 1024-dimensional model
    DEFAULT_MODEL = "mixedbread-ai/mxbai-embed-large-v1"
    
    # Worker-safe singleton pattern for model caching
    _model_cache = {}
    _model_lock = threading.Lock()
    
    # Model configuration for different HuggingFace models
    MODEL_CONFIGS = {
        "mixedbread-ai/mxbai-embed-large-v1": {
            "dimensions": 1024,
            "query_prefix": "Represent this sentence for searching relevant passages: ",
            "document_prefix": "",
            "truncate_dim": 1024  # Use Matryoshka learning to get 1024 dims
        },
        "dunzhang/stella_en_1.5B_v5": {
            "dimensions": 1024,
            "query_prefix": "",
            "document_prefix": "",
            "trust_remote_code": True
        },
        "BAAI/bge-large-en-v1.5": {
            "dimensions": 1024,
            "query_prefix": "Represent this sentence for searching relevant passages: ",
            "document_prefix": ""
        },
        # Fallback smaller model for development/testing
        "sentence-transformers/all-MiniLM-L6-v2": {
            "dimensions": 384,
            "target_dimensions": 1024,  # Pad to 1024 for database compatibility
            "query_prefix": "",
            "document_prefix": ""
        }
    }
    
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or os.getenv("HUGGINGFACE_MODEL", self.DEFAULT_MODEL)
        
        # Get model configuration
        self.config = self.MODEL_CONFIGS.get(self.model_name, {
            "dimensions": 1024,  # Default assumption
            "query_prefix": "",
            "document_prefix": ""
        })
        
        # DON'T load the model here - use lazy loading instead
        self.model = None
        logger.info(f"Configured HuggingFace embeddings for model: {self.model_name} (lazy loading)")
    
    def _get_model(self):
        """Thread-safe lazy model loading with caching"""
        # Check if model is already loaded for this instance
        if self.model is not None:
            return self.model
            
        # Use thread-safe singleton pattern for model caching
        with self._model_lock:
            # Check cache first (across all instances)
            if self.model_name in self._model_cache:
                self.model = self._model_cache[self.model_name]
                return self.model
            
            try:
                logger.info(f"Loading HuggingFace model: {self.model_name}")
                
                # Import here to avoid issues during worker startup
                from sentence_transformers import SentenceTransformer
                import torch
                
                # Force CPU to avoid CUDA issues in workers
                device = 'cpu'
                logger.info(f"Loading model on device: {device}")
                
                # Load model with specific configuration
                model_kwargs = {
                    'device': device,
                    'cache_folder': os.getenv('TRANSFORMERS_CACHE', None)
                }
                if "trust_remote_code" in self.config:
                    model_kwargs["trust_remote_code"] = self.config["trust_remote_code"]
                
                model = SentenceTransformer(self.model_name, **model_kwargs)
                
                # Set to evaluation mode and disable gradients for inference
                model.eval()
                torch.set_grad_enabled(False)
                
                # Set truncate_dim for Matryoshka models
                if "truncate_dim" in self.config:
                    model.truncate_dim = self.config["truncate_dim"]
                
                # Verify dimensions with a test embedding
                test_embedding = model.encode("test", convert_to_numpy=True, show_progress_bar=False)
                actual_dims = len(test_embedding)
                
                if actual_dims != self.config["dimensions"]:
                    logger.warning(
                        f"Model {self.model_name} produced {actual_dims} dimensions, "
                        f"expected {self.config['dimensions']}"
                    )
                    self.config["dimensions"] = actual_dims
                
                # Cache the model for reuse
                self._model_cache[self.model_name] = model
                self.model = model
                
                logger.info(
                    f"Successfully loaded HuggingFace model: {self.model_name} "
                    f"({self.config['dimensions']} dimensions) on {device}"
                )
                
                return model
                
            except ImportError as e:
                logger.error(f"Failed to import sentence-transformers: {e}")
                # Fallback to LangChain if SentenceTransformer is not available
                logger.warning("sentence-transformers not available, falling back to LangChain wrapper")
                try:
                    from langchain_huggingface import HuggingFaceEmbeddings as HFEmbeddings
                    
                    model = HFEmbeddings(model_name=self.model_name)
                    # Test to get actual dimensions
                    test_embedding = model.embed_query("test")
                    self.config["dimensions"] = len(test_embedding)
                    
                    # Cache the model
                    self._model_cache[self.model_name] = model
                    self.model = model
                    
                    logger.info(
                        f"Initialized HuggingFace embeddings (LangChain) with model: {self.model_name} "
                        f"({self.config['dimensions']} dimensions)"
                    )
                    return model
                    
                except ImportError as e2:
                    logger.error(f"Failed to import langchain-huggingface: {e2}")
                    raise ImportError(
                        "Neither sentence-transformers nor langchain-huggingface available. "
                        "Install with: pip install sentence-transformers>=3.0.0"
                    )
                    
            except Exception as e:
                logger.error(f"Failed to load model {self.model_name}: {e}")
                raise RuntimeError(f"Model loading failed: {e}")
    
    def _pad_embedding(self, embedding: List[float]) -> List[float]:
        """Pad embedding to target dimensions if needed"""
        target_dims = self.config.get("target_dimensions", self.config["dimensions"])
        if len(embedding) < target_dims:
            # Pad with zeros to reach target dimensions
            return embedding + [0.0] * (target_dims - len(embedding))
        elif len(embedding) > target_dims:
            # Truncate if somehow larger
            return embedding[:target_dims]
        return embedding
    
    def embed_texts(self, texts: List[str], progress_callback=None) -> List[List[float]]:
        """Generate embeddings for a list of texts with enhanced error handling and progress tracking"""
        if not texts:
            return []
        
        # Filter out empty texts and track indices
        non_empty_texts = []
        non_empty_indices = []
        for i, text in enumerate(texts):
            if text and text.strip():
                # Add document prefix if specified
                doc_text = self.config.get("document_prefix", "") + text.strip()
                non_empty_texts.append(doc_text)
                non_empty_indices.append(i)
        
        target_dims = self.config.get("target_dimensions", self.config["dimensions"])
        if not non_empty_texts:
            logger.warning("All texts were empty, returning zero embeddings")
            return [[0.0] * target_dims for _ in texts]
        
        try:
            # Get model with lazy loading
            model = self._get_model()
            
            # Process in batches for better memory management and progress tracking
            batch_size = int(os.getenv("EMBED_BATCH_SIZE", "96"))  # Configurable batch size
            all_embeddings = []
            
            for i in range(0, len(non_empty_texts), batch_size):
                batch = non_empty_texts[i:i + batch_size]
                
                try:
                    # Use timeout to prevent hangs
                    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
                    
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        if hasattr(model, 'encode'):
                            # SentenceTransformer method
                            future = executor.submit(
                                model.encode,
                                batch,
                                convert_to_numpy=True,
                                show_progress_bar=False,
                                batch_size=len(batch)
                            )
                        else:
                            # LangChain method
                            future = executor.submit(model.embed_documents, batch)
                        
                        try:
                            batch_embeddings = future.result(timeout=300)  # 5 min timeout per batch for CPU models
                            if hasattr(model, 'encode'):
                                batch_embeddings = batch_embeddings.tolist()
                            all_embeddings.extend(batch_embeddings)
                            
                        except FutureTimeoutError:
                            logger.error(f"Timeout embedding batch of {len(batch)} texts")
                            # Fallback: zero embeddings for timed-out batch
                            all_embeddings.extend([[0.0] * target_dims for _ in batch])
                    
                    # Report progress
                    if progress_callback:
                        progress = min(100, int((i + len(batch)) / len(non_empty_texts) * 100))
                        progress_callback(progress)
                        
                except Exception as e:
                    logger.error(f"Error embedding batch {i//batch_size + 1}: {e}")
                    # Fallback: zero embeddings for failed batch
                    all_embeddings.extend([[0.0] * target_dims for _ in batch])
            
            # Reconstruct full list with zeros for empty texts
            full_embeddings = []
            embedding_idx = 0
            for i in range(len(texts)):
                if i in non_empty_indices:
                    if embedding_idx < len(all_embeddings):
                        padded_embedding = self._pad_embedding(all_embeddings[embedding_idx])
                        full_embeddings.append(padded_embedding)
                    else:
                        # Safety fallback
                        full_embeddings.append([0.0] * target_dims)
                    embedding_idx += 1
                else:
                    full_embeddings.append([0.0] * target_dims)
            
            return full_embeddings
            
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            # Return zero embeddings as fallback
            return [[0.0] * target_dims for _ in texts]
    
    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a search query"""
        target_dims = self.config.get("target_dimensions", self.config["dimensions"])
        if not query or not query.strip():
            return [0.0] * target_dims
        
        try:
            # Get model with lazy loading
            model = self._get_model()
            
            # Add query prefix if specified
            query_text = self.config.get("query_prefix", "") + query.strip()
            
            # Use timeout to prevent hangs
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
            
            with ThreadPoolExecutor(max_workers=1) as executor:
                if hasattr(model, 'encode'):
                    # SentenceTransformer method
                    future = executor.submit(
                        model.encode,
                        query_text,
                        convert_to_numpy=True,
                        show_progress_bar=False
                    )
                else:
                    # LangChain method
                    future = executor.submit(model.embed_query, query_text)
                
                try:
                    embedding = future.result(timeout=60)  # 60s timeout for single query on CPU
                    if hasattr(model, 'encode'):
                        embedding = embedding.tolist()
                        
                except FutureTimeoutError:
                    logger.error(f"Timeout embedding query: {query[:100]}...")
                    return [0.0] * target_dims
            
            # Pad embedding to target dimensions
            return self._pad_embedding(embedding)
            
        except Exception as e:
            logger.error(f"Error generating query embedding: {e}")
            return [0.0] * target_dims
    
    def get_embedding_info(self) -> Dict[str, Any]:
        """Get information about the embedding model"""
        target_dims = self.config.get("target_dimensions", self.config["dimensions"])
        return {
            "model": self.model_name,
            "dimension": target_dims,  # Report target dimensions (padded)
            "actual_dimension": self.config["dimensions"],  # Report actual model dimensions
            "batch_size": "unlimited",  # HuggingFace handles batching internally
            "provider": "huggingface",
            "query_prefix": self.config.get("query_prefix", ""),
            "document_prefix": self.config.get("document_prefix", ""),
            "loaded": self.model is not None,
            "cached_models": list(self._model_cache.keys())
        }
    
    @classmethod
    def cleanup_models(cls):
        """Clean up cached models to free memory"""
        with cls._model_lock:
            if cls._model_cache:
                logger.info(f"Cleaning up {len(cls._model_cache)} cached models")
                cls._model_cache.clear()
                
                # Force garbage collection
                import gc
                gc.collect()
                
                logger.info("Model cleanup completed")


class OpenAIEmbeddings(BaseEmbeddings):
    """OpenAI embeddings implementation using text-embedding-3-small"""
    
    MODEL = "text-embedding-3-small"
    EMBEDDING_DIM = 1536
    BATCH_SIZE = 2048  # OpenAI's max texts per request
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY required for OpenAI embeddings provider")
        
        try:
            import openai
            self.client = openai.OpenAI(api_key=self.api_key)
            logger.info(f"Initialized OpenAI embeddings with model: {self.MODEL}")
        except ImportError:
            raise ImportError("openai package required for OpenAI embeddings. Install with: pip install openai")
    
    def embed_texts(self, texts: List[str], **kwargs) -> List[List[float]]:
        """Generate embeddings for a list of texts with automatic batching"""
        if not texts:
            return []
        
        # Remove empty texts and track their indices
        non_empty_texts = []
        non_empty_indices = []
        for i, text in enumerate(texts):
            if text and text.strip():
                non_empty_texts.append(text.strip())
                non_empty_indices.append(i)
        
        if not non_empty_texts:
            logger.warning("All texts were empty, returning zero embeddings")
            return [[0.0] * self.EMBEDDING_DIM for _ in texts]
        
        all_embeddings = []
        
        # Process in batches
        for i in range(0, len(non_empty_texts), self.BATCH_SIZE):
            batch = non_empty_texts[i:i + self.BATCH_SIZE]
            try:
                response = self.client.embeddings.create(
                    input=batch,
                    model=self.MODEL
                )
                batch_embeddings = [embedding.embedding for embedding in response.data]
                all_embeddings.extend(batch_embeddings)
                logger.debug(f"Successfully embedded batch of {len(batch)} texts")
            except Exception as e:
                logger.error(f"Error embedding batch: {e}")
                # Return zero embeddings for failed batch
                all_embeddings.extend([[0.0] * self.EMBEDDING_DIM for _ in batch])
        
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
        
        return full_embeddings
    
    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a search query"""
        if not query or not query.strip():
            return [0.0] * self.EMBEDDING_DIM
        
        embeddings = self.embed_texts([query])
        return embeddings[0]
    
    def get_embedding_info(self) -> Dict[str, Any]:
        """Get information about the embedding model"""
        return {
            "model": self.MODEL,
            "dimension": self.EMBEDDING_DIM,
            "batch_size": self.BATCH_SIZE,
            "provider": "openai"
        }


class FlexibleEmbeddings:
    """
    Factory class that returns the appropriate embeddings provider
    based on environment configuration
    """
    
    @staticmethod
    def get_embeddings(
        provider: Optional[str] = None,
        **kwargs
    ) -> BaseEmbeddings:
        """
        Get embeddings instance based on provider configuration
        
        Args:
            provider: Override provider selection (default: from env)
            **kwargs: Additional arguments passed to provider
            
        Returns:
            BaseEmbeddings instance
        """
        # Determine provider
        if provider is None:
            provider = os.getenv("EMBEDDINGS_PROVIDER", "cohere").lower()
        
        # Create appropriate instance
        if provider == "cohere":
            api_key = kwargs.get("api_key") or os.getenv("COHERE_API_KEY")
            if not api_key:
                raise ValueError(
                    "COHERE_API_KEY required for Cohere embeddings provider"
                )
            return CohereEmbeddings(api_key=api_key)
        
        elif provider == "openai":
            api_key = kwargs.get("api_key") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY required for OpenAI embeddings provider"
                )
            return OpenAIEmbeddings(api_key=api_key)
        
        elif provider == "huggingface":
            model_name = kwargs.get("model_name") or os.getenv("HUGGINGFACE_MODEL")
            return HuggingFaceEmbeddings(model_name=model_name)
        
        else:
            raise ValueError(
                f"Unknown embeddings provider: {provider}. "
                "Supported providers: cohere, openai, huggingface"
            )


# Singleton instance management
_embeddings_instance: Optional[BaseEmbeddings] = None


def get_embeddings() -> BaseEmbeddings:
    """
    Get or create the singleton embeddings instance based on configuration
    
    Returns:
        BaseEmbeddings instance
    """
    global _embeddings_instance
    if _embeddings_instance is None:
        _embeddings_instance = FlexibleEmbeddings.get_embeddings()
    return _embeddings_instance


# Create singleton instance for import compatibility
embeddings_manager = get_embeddings()


# Example usage:
if __name__ == "__main__":
    # Test with different providers
    
    # Use environment configuration
    embeddings = get_embeddings()
    print(f"Using {embeddings.get_embedding_info()['provider']} provider")
    
    # Test embedding
    test_texts = ["Hello world", "This is a test"]
    embeddings_result = embeddings.embed_texts(test_texts)
    print(f"Embedded {len(test_texts)} texts")
    print(f"Embedding dimensions: {len(embeddings_result[0])}")
    
    # Test query embedding
    query_embedding = embeddings.embed_query("test query")
    print(f"Query embedding dimension: {len(query_embedding)}")
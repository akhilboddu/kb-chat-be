"""
Contextualizer for Contextual RAG
Generates contextual descriptions for chunks to improve retrieval quality
Based on Anthropic's Contextual Retrieval approach
"""

import os
import hashlib
from typing import Optional, Tuple, Dict, Any
from functools import lru_cache
import logging
import time

# Try to import Anthropic first, then OpenAI as fallback
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    
import openai

logger = logging.getLogger(__name__)


class Contextualizer:
    """
    Generates contextual descriptions for document chunks.
    Uses Anthropic Claude as primary, OpenAI as fallback.
    Implements caching to reduce API calls and costs.
    """
    
    # Prompt template based on Anthropic's recommendations
    CONTEXT_PROMPT_TEMPLATE = """<document>
{full_document}
</document>

Here is the chunk we want to contextualize:
<chunk>
{chunk}
</chunk>

Please provide a brief, informative context (50-100 tokens) for this chunk that explains:
1. What this chunk is about
2. How it relates to the overall document
3. Any key concepts or entities mentioned

Write the context as if it's a prefix to the chunk, starting with "This section discusses..." or similar.
Keep it concise and factual. Do not include the chunk content itself in your response."""

    def __init__(
        self, 
        anthropic_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        prefer_anthropic: bool = True,
        cache_size: int = 10000
    ):
        """
        Initialize the contextualizer.
        
        Args:
            anthropic_api_key: Anthropic API key (uses env var if not provided)
            openai_api_key: OpenAI API key (uses env var if not provided)
            prefer_anthropic: Use Anthropic if available, otherwise OpenAI
            cache_size: Maximum number of contexts to cache
        """
        self.prefer_anthropic = prefer_anthropic and ANTHROPIC_AVAILABLE
        
        # Initialize Anthropic client if available
        if ANTHROPIC_AVAILABLE:
            self.anthropic_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
            if self.anthropic_key:
                self.anthropic_client = anthropic.Anthropic(api_key=self.anthropic_key)
                logger.info("Initialized Anthropic client for contextualization")
            else:
                self.anthropic_client = None
                logger.warning("Anthropic API key not found")
        else:
            self.anthropic_client = None
            logger.warning("Anthropic library not installed")
        
        # Initialize OpenAI client as fallback
        self.openai_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if self.openai_key:
            openai.api_key = self.openai_key
            self.openai_client = openai.OpenAI(api_key=self.openai_key)
            logger.info("Initialized OpenAI client for contextualization")
        else:
            self.openai_client = None
            logger.warning("OpenAI API key not found")
        
        if not self.anthropic_client and not self.openai_client:
            raise ValueError("At least one of ANTHROPIC_API_KEY or OPENAI_API_KEY must be set")
        
        # Set up LRU cache
        self._create_context_cached = lru_cache(maxsize=cache_size)(self._create_context_impl)
        
    def create_context(self, full_document: str, chunk: str) -> str:
        """
        Generate context for a chunk within a document.
        Uses caching to avoid redundant API calls.
        
        Args:
            full_document: The complete document text
            chunk: The specific chunk to contextualize
            
        Returns:
            Context string (50-100 tokens)
        """
        # Create cache key from hash of inputs
        cache_key = self._create_cache_key(full_document, chunk)
        
        try:
            # Use cached function
            return self._create_context_cached(cache_key, full_document, chunk)
        except Exception as e:
            logger.error(f"Error creating context: {e}")
            # Return a generic context on error
            return "This section contains information from the document."
    
    def _create_cache_key(self, full_document: str, chunk: str) -> str:
        """Create a cache key from document and chunk."""
        content = f"{full_document}|||{chunk}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _create_context_impl(self, cache_key: str, full_document: str, chunk: str) -> str:
        """
        Internal implementation that actually calls the LLM.
        This method is wrapped by LRU cache.
        
        Args:
            cache_key: Hash key (required by cache but not used in logic)
            full_document: The complete document
            chunk: The chunk to contextualize
            
        Returns:
            Context string
        """
        # Prepare the prompt
        prompt = self.CONTEXT_PROMPT_TEMPLATE.format(
            full_document=full_document[:8000],  # Limit document size
            chunk=chunk[:2000]  # Limit chunk size
        )
        
        # Try Anthropic first if preferred and available
        if self.prefer_anthropic and self.anthropic_client:
            try:
                context = self._call_anthropic(prompt)
                if context:
                    return context
            except Exception as e:
                logger.warning(f"Anthropic call failed, falling back to OpenAI: {e}")
        
        # Fall back to OpenAI
        if self.openai_client:
            try:
                context = self._call_openai(prompt)
                if context:
                    return context
            except Exception as e:
                logger.error(f"OpenAI call also failed: {e}")
        
        # If both fail, return generic context
        return "This section contains information from the document."
    
    def _call_anthropic(self, prompt: str) -> Optional[str]:
        """
        Call Anthropic Claude to generate context.
        
        Args:
            prompt: The contextualization prompt
            
        Returns:
            Context string or None if failed
        """
        if not self.anthropic_client:
            return None
        
        try:
            response = self.anthropic_client.messages.create(
                model="claude-3-haiku-20240307",  # Fast and cost-effective
                max_tokens=150,  # Allow some buffer for 50-100 token target
                temperature=0.3,  # Low temperature for consistency
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            context = response.content[0].text.strip()
            logger.debug(f"Generated context via Anthropic: {len(context.split())} words")
            return context
            
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return None
    
    def _call_openai(self, prompt: str) -> Optional[str]:
        """
        Call OpenAI to generate context.
        
        Args:
            prompt: The contextualization prompt
            
        Returns:
            Context string or None if failed
        """
        if not self.openai_client:
            return None
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",  # Fast and cost-effective
                max_tokens=150,  # Allow some buffer
                temperature=0.3,  # Low temperature for consistency
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that creates brief, informative contexts for document chunks."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            context = response.choices[0].message.content.strip()
            logger.debug(f"Generated context via OpenAI: {len(context.split())} words")
            return context
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None
    
    def clear_cache(self):
        """Clear the context cache."""
        self._create_context_cached.cache_clear()
        logger.info("Cleared context cache")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the cache."""
        info = self._create_context_cached.cache_info()
        return {
            "hits": info.hits,
            "misses": info.misses,
            "max_size": info.maxsize,
            "current_size": info.currsize,
            "hit_rate": info.hits / (info.hits + info.misses) if (info.hits + info.misses) > 0 else 0
        }
    
    def batch_create_contexts(
        self, 
        full_document: str, 
        chunks: list[str],
        show_progress: bool = True
    ) -> list[str]:
        """
        Create contexts for multiple chunks from the same document.
        
        Args:
            full_document: The complete document
            chunks: List of chunks to contextualize
            show_progress: Whether to log progress
            
        Returns:
            List of contexts corresponding to each chunk
        """
        contexts = []
        total = len(chunks)
        
        for i, chunk in enumerate(chunks):
            if show_progress and i % 10 == 0:
                logger.info(f"Generating contexts: {i}/{total} ({i/total*100:.1f}%)")
            
            context = self.create_context(full_document, chunk)
            contexts.append(context)
            
            # Small delay to avoid rate limits
            if i > 0 and i % 20 == 0:
                time.sleep(0.1)
        
        if show_progress:
            logger.info(f"Generated {total} contexts. Cache stats: {self.get_cache_info()}")
        
        return contexts


# Singleton instance
_contextualizer_instance = None

def get_contextualizer() -> Contextualizer:
    """
    Get or create the singleton Contextualizer instance.
    
    Returns:
        Contextualizer instance
    """
    global _contextualizer_instance
    if _contextualizer_instance is None:
        _contextualizer_instance = Contextualizer()
    return _contextualizer_instance

# Create singleton instance for import
contextualizer = get_contextualizer() 
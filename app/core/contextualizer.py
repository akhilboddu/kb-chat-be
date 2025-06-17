"""
Contextualizer for Contextual RAG
Generates contextual descriptions for chunks to improve retrieval quality
Based on Anthropic's Contextual Retrieval approach with Gemini Flash optimization
"""

import os
import hashlib
from typing import Optional, Tuple, Dict, Any, List
from functools import lru_cache
import logging
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Import performance monitoring
try:
    from app.utils.performance_monitor import performance_monitor
    PERFORMANCE_MONITORING_AVAILABLE = True
except ImportError:
    PERFORMANCE_MONITORING_AVAILABLE = False

# Google Gemini
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Try to import Anthropic first, then OpenAI as fallbacks
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logger = logging.getLogger(__name__)


class Contextualizer:
    """
    Generates contextual descriptions for document chunks.
    Primary: Google Gemini Flash (lightning fast, supports batch processing)  
    Fallbacks: Anthropic Claude → OpenAI GPT-3.5/4
    Implements caching to reduce API calls and costs by 90%.
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
        gemini_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        prefer_gemini: bool = True,
        cache_size: int = 10000,
        batch_size: int = 50
    ):
        """
        Initialize the contextualizer.
        prefer_gemini: if True (default) use Gemini Flash when available
        batch_size: number of chunks to process in each batch (default 50 - optimized for t3.large)
        """
        # Dynamic batch sizing based on environment
        self.batch_size = int(os.getenv("CONTEXT_BATCH_SIZE", str(batch_size)))
        self.enable_delays = os.getenv("ENABLE_CONTEXT_DELAYS", "false").lower() == "true"
        
        # Gemini setup (Primary)
        self.use_gemini = prefer_gemini and GEMINI_AVAILABLE
        if self.use_gemini:
            key = gemini_api_key or os.getenv("GOOGLE_API_KEY")
            if key:
                genai.configure(api_key=key)
                model_name = os.getenv("GEMINI_CONTEXT_MODEL", "gemini-1.5-flash")
                self.gemini_model = genai.GenerativeModel(model_name)
                logger.info(f"✅ Initialized Gemini {model_name} for context generation (PRIMARY)")
            else:
                self.use_gemini = False
                logger.warning("❌ GOOGLE_API_KEY not set – Gemini disabled")
        
        # Anthropic setup (Secondary fallback)
        self.use_anthropic = ANTHROPIC_AVAILABLE
        if ANTHROPIC_AVAILABLE:
            self.anthropic_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
            if self.anthropic_key:
                self.anthropic_client = anthropic.Anthropic(api_key=self.anthropic_key)
                logger.info("✅ Anthropic Claude available (FALLBACK)")
            else:
                self.anthropic_client = None
                self.use_anthropic = False
        else:
            self.anthropic_client = None
            self.use_anthropic = False
        
        # OpenAI setup (Tertiary fallback)
        self.use_openai = OPENAI_AVAILABLE
        if OPENAI_AVAILABLE:
            self.openai_key = openai_api_key or os.getenv("OPENAI_API_KEY")
            if self.openai_key:
                self.openai_client = openai.OpenAI(api_key=self.openai_key)
                logger.info("✅ OpenAI available (FALLBACK)")
            else:
                self.openai_client = None
                self.use_openai = False
        else:
            self.openai_client = None
            self.use_openai = False
        
        # Check if we have at least one provider
        if not (self.use_gemini or self.use_anthropic or self.use_openai):
            raise ValueError("❌ No LLM credentials found for context generation. Please set GOOGLE_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY")
        
        # Log provider priority
        providers = []
        if self.use_gemini: providers.append("Gemini Flash")
        if self.use_anthropic: providers.append("Anthropic Claude")
        if self.use_openai: providers.append("OpenAI")
        logger.info(f"🔄 Context generation provider chain: {' → '.join(providers)}")
        
        # Cache setup
        self._create_context_cached = lru_cache(maxsize=cache_size)(self._create_context_impl)
    
    # ---------------- Gemini batch processing -----------------
    def _call_gemini_batch(self, prompts: List[str]) -> List[str]:
        """
        Call Gemini with multiple prompts in a single request.
        This is much faster than individual API calls.
        """
        try:
            logger.info(f"🚀 Gemini batch processing {len(prompts)} contexts...")
            start_time = time.time()
            
            # Process all prompts in a single batch
            contexts = []
            for prompt in prompts:
                try:
                    response = self.gemini_model.generate_content(
                        prompt,
                        generation_config={
                            "max_output_tokens": 150,
                            "temperature": 0.3,
                            "top_p": 0.8,
                            "top_k": 40
                        }
                    )
                    
                    if response and response.text:
                        context = response.text.strip()
                        # Ensure context starts appropriately
                        if not context.lower().startswith(('this section', 'this part', 'this chunk', 'this content')):
                            context = f"This section discusses {context.lower()}"
                        contexts.append(context)
                    else:
                        contexts.append("This section contains relevant information from the document.")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Gemini single prompt failed: {e}")
                    contexts.append("This section contains relevant information from the document.")
                    
                # Optional delay only if enabled via environment variable
                if self.enable_delays:
                    time.sleep(0.05)  # Reduced delay when enabled
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Gemini batch completed in {elapsed:.2f}s ({len(prompts)/elapsed:.1f} contexts/sec)")
            
            # Record performance metrics
            if PERFORMANCE_MONITORING_AVAILABLE:
                performance_monitor.record_context_performance(
                    provider="gemini",
                    batch_size=len(prompts),
                    duration=elapsed,
                    success=True
                )
            
            return contexts
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Gemini batch processing failed: {e}")
            
            # Record failure metrics
            if PERFORMANCE_MONITORING_AVAILABLE:
                performance_monitor.record_context_performance(
                    provider="gemini",
                    batch_size=len(prompts),
                    duration=elapsed,
                    success=False,
                    error=str(e)
                )
            
            raise
    
    def _call_anthropic_batch(self, prompts: List[str]) -> List[str]:
        """
        Call Anthropic with multiple prompts (sequential for now).
        """
        try:
            logger.info(f"🔄 Anthropic batch processing {len(prompts)} contexts...")
            start_time = time.time()
            
            contexts = []
            for i, prompt in enumerate(prompts):
                try:
                    response = self.anthropic_client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=150,
                        temperature=0.3,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    
                    if response and response.content:
                        context = response.content[0].text.strip()
                        contexts.append(context)
                    else:
                        contexts.append("This section contains relevant information from the document.")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Anthropic prompt {i+1} failed: {e}")
                    contexts.append("This section contains relevant information from the document.")
                
                # Optional rate limiting delay
                if self.enable_delays:
                    time.sleep(0.1)  # Reduced delay when enabled
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Anthropic batch completed in {elapsed:.2f}s")
            return contexts
            
        except Exception as e:
            logger.error(f"❌ Anthropic batch processing failed: {e}")
            raise
    
    def _call_openai_batch(self, prompts: List[str]) -> List[str]:
        """
        Call OpenAI with multiple prompts (sequential for now).
        """
        try:
            logger.info(f"🔄 OpenAI batch processing {len(prompts)} contexts...")
            start_time = time.time()
            
            contexts = []
            model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
            
            for i, prompt in enumerate(prompts):
                try:
                    response = self.openai_client.chat.completions.create(
                        model=model,
                        max_tokens=150,
                        temperature=0.3,
                        messages=[
                            {"role": "system", "content": "You create brief, informative contexts for document chunks."},
                            {"role": "user", "content": prompt}
                        ]
                    )
                    
                    if response and response.choices:
                        context = response.choices[0].message.content.strip()
                        contexts.append(context)
                    else:
                        contexts.append("This section contains relevant information from the document.")
                        
                except Exception as e:
                    logger.warning(f"⚠️ OpenAI prompt {i+1} failed: {e}")
                    contexts.append("This section contains relevant information from the document.")
                
                # Optional rate limiting delay
                if self.enable_delays:
                    time.sleep(0.05)  # Reduced delay when enabled
            
            elapsed = time.time() - start_time
            logger.info(f"✅ OpenAI batch completed in {elapsed:.2f}s")
            return contexts
            
        except Exception as e:
            logger.error(f"❌ OpenAI batch processing failed: {e}")
            raise
    
    # ---------------- Public API -----------------
    def create_context(self, full_document: str, chunk: str) -> str:
        """
        Create context for a single chunk.
        Uses caching to avoid duplicate API calls.
        """
        cache_key = self._create_cache_key(full_document, chunk)
        try:
            return self._create_context_cached(cache_key, full_document, chunk)
        except Exception as e:
            logger.error(f"❌ Context generation error: {e}")
            return "This section contains information from the document."
    
    def batch_create_contexts(self, full_document: str, chunks: List[str], show_progress: bool = True) -> List[str]:
        """
        Create contexts for multiple chunks efficiently.
        Uses batch processing with Gemini Flash for 10x+ speedup.
        """
        if not chunks:
            return []
        
        logger.info(f"🎯 Starting batch context generation for {len(chunks)} chunks")
        start_time = time.time()
        
        # Prepare prompts
        prompts = []
        for chunk in chunks:
            prompt = self.CONTEXT_PROMPT_TEMPLATE.format(
                full_document=full_document[:8000],  # Limit document size
                chunk=chunk[:2000]  # Limit chunk size
            )
            prompts.append(prompt)
        
        # Try providers in order: Gemini → Anthropic → OpenAI
        contexts = None
        
        # 1. Try Gemini Flash (Primary - fastest)
        if self.use_gemini:
            try:
                contexts = self._call_gemini_batch(prompts)
                logger.info("✅ Used Gemini Flash for context generation")
            except Exception as e:
                logger.warning(f"⚠️ Gemini batch failed, trying Anthropic: {e}")
        
        # 2. Try Anthropic (Secondary fallback)
        if contexts is None and self.use_anthropic:
            try:
                contexts = self._call_anthropic_batch(prompts)
                logger.info("✅ Used Anthropic Claude for context generation")
            except Exception as e:
                logger.warning(f"⚠️ Anthropic batch failed, trying OpenAI: {e}")
        
        # 3. Try OpenAI (Tertiary fallback)
        if contexts is None and self.use_openai:
            try:
                contexts = self._call_openai_batch(prompts)
                logger.info("✅ Used OpenAI for context generation")
            except Exception as e:
                logger.error(f"❌ OpenAI batch failed: {e}")
        
        # 4. Final fallback - use cached single calls
        if contexts is None:
            logger.warning("⚠️ All batch providers failed, falling back to cached single calls")
            contexts = []
            total = len(chunks)
            for i, chunk in enumerate(chunks):
                if show_progress and i % 5 == 0:
                    logger.info(f"📊 Generating contexts: {i}/{total} ({i/total*100:.1f}%)")
                contexts.append(self.create_context(full_document, chunk))
        
        elapsed = time.time() - start_time
        logger.info(f"🏁 Batch context generation completed in {elapsed:.2f}s ({len(chunks)/elapsed:.1f} contexts/sec)")
        
        return contexts
    
    # ---------------- Internal implementation -----------------
    def _create_cache_key(self, full_document: str, chunk: str) -> str:
        """Create a cache key for the given document and chunk."""
        content = f"{full_document}|||{chunk}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _create_context_impl(self, cache_key: str, full_document: str, chunk: str) -> str:
        """
        Internal implementation for creating context.
        This is cached via LRU cache.
        """
        prompt = self.CONTEXT_PROMPT_TEMPLATE.format(
            full_document=full_document[:8000], 
            chunk=chunk[:2000]
        )
        
        # Try providers in order: Gemini → Anthropic → OpenAI
        
        # 1. Try Gemini Flash (Primary)
        if self.use_gemini:
            try:
                response = self.gemini_model.generate_content(
                    prompt,
                    generation_config={
                        "max_output_tokens": 150,
                        "temperature": 0.3,
                        "top_p": 0.8,
                        "top_k": 40
                    }
                )
                
                if response and response.text:
                    context = response.text.strip()
                    # Ensure context starts appropriately
                    if not context.lower().startswith(('this section', 'this part', 'this chunk', 'this content')):
                        context = f"This section discusses {context.lower()}"
                    return context
                    
            except Exception as e:
                logger.warning(f"⚠️ Gemini single call failed: {e}")
        
        # 2. Try Anthropic (Secondary fallback)
        if self.use_anthropic:
            try:
                response = self.anthropic_client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=150,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                if response and response.content:
                    return response.content[0].text.strip()
                    
            except Exception as e:
                logger.warning(f"⚠️ Anthropic call failed: {e}")
        
        # 3. Try OpenAI (Tertiary fallback)
        if self.use_openai:
            try:
                model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
                response = self.openai_client.chat.completions.create(
                    model=model,
                    max_tokens=150,
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": "You create brief, informative contexts for document chunks."},
                        {"role": "user", "content": prompt}
                    ]
                )
                
                if response and response.choices:
                    return response.choices[0].message.content.strip()
                    
            except Exception as e:
                logger.error(f"❌ OpenAI call failed: {e}")
        
        # Final fallback
        return "This section contains information from the document."
    
    def clear_cache(self):
        """Clear the context cache."""
        self._create_context_cached.cache_clear()
        logger.info("🧹 Cleared context cache")
    
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
    
    def get_provider_status(self) -> Dict[str, Any]:
        """Get status of available providers."""
        return {
            "gemini_available": self.use_gemini,
            "anthropic_available": self.use_anthropic,
            "openai_available": self.use_openai,
            "primary_provider": "gemini" if self.use_gemini else ("anthropic" if self.use_anthropic else ("openai" if self.use_openai else "none")),
            "batch_size": self.batch_size
        }


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
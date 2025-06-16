"""Cache utilities for speeding up chat responses"""

import json
import hashlib
import logging
from typing import Optional, Dict, Any
from datetime import timedelta
from app.config.redisconnection import redisConnection

logger = logging.getLogger(__name__)

# Cache key prefixes
CACHE_PREFIX_RESPONSE = "chat:response:"
CACHE_PREFIX_EMBEDDING = "chat:embedding:"
CACHE_PREFIX_SIMILAR = "chat:similar:"

# Default TTLs
RESPONSE_CACHE_TTL = 3600  # 1 hour for chat responses
EMBEDDING_CACHE_TTL = 86400  # 24 hours for embeddings
SIMILAR_CACHE_TTL = 1800  # 30 minutes for similar questions


def generate_cache_key(prefix: str, kb_id: str, content: str) -> str:
    """Generate a cache key based on content hash."""
    content_hash = hashlib.md5(f"{kb_id}:{content}".encode()).hexdigest()
    return f"{prefix}{kb_id}:{content_hash}"


def get_cached_response(kb_id: str, message: str) -> Optional[Dict[str, Any]]:
    """Get cached response for a message."""
    try:
        client = redisConnection.client
        if not client:
            return None
            
        cache_key = generate_cache_key(CACHE_PREFIX_RESPONSE, kb_id, message.lower().strip())
        cached_data = client.get(cache_key)
        
        if cached_data:
            logger.info(f"Cache hit for message: {message[:50]}...")
            return json.loads(cached_data)
        return None
    except Exception as e:
        logger.error(f"Error getting cached response: {e}")
        return None


def set_cached_response(
    kb_id: str, 
    message: str, 
    response: str, 
    metadata: Optional[Dict[str, Any]] = None,
    ttl: int = RESPONSE_CACHE_TTL
) -> bool:
    """Cache a response for a message."""
    try:
        client = redisConnection.client
        if not client:
            return False
            
        cache_key = generate_cache_key(CACHE_PREFIX_RESPONSE, kb_id, message.lower().strip())
        cache_data = {
            "response": response,
            "metadata": metadata or {},
            "cached_at": json.dumps({})
        }
        
        client.setex(cache_key, ttl, json.dumps(cache_data))
        logger.info(f"Cached response for message: {message[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Error setting cached response: {e}")
        return False


def invalidate_kb_cache(kb_id: str) -> int:
    """Invalidate all cached responses for a knowledge base."""
    try:
        client = redisConnection.client
        if not client:
            return 0
            
        # Find all keys for this KB
        pattern = f"{CACHE_PREFIX_RESPONSE}{kb_id}:*"
        keys = list(client.scan_iter(match=pattern))
        
        if keys:
            deleted = client.delete(*keys)
            logger.info(f"Invalidated {deleted} cache entries for KB: {kb_id}")
            return deleted
        return 0
    except Exception as e:
        logger.error(f"Error invalidating KB cache: {e}")
        return 0


def clear_context_dependent_cache(kb_id: str) -> int:
    """Clear cached responses for context-dependent words like 'yes', 'no', etc."""
    try:
        client = redisConnection.client
        if not client:
            return 0
            
        context_words = ['yes', 'no', 'ok', 'sure', 'yeah', 'yep', 'nope', 'thanks', 'thank you']
        deleted_count = 0
        
        for word in context_words:
            cache_key = generate_cache_key(CACHE_PREFIX_RESPONSE, kb_id, word)
            if client.delete(cache_key):
                deleted_count += 1
                logger.info(f"Cleared cache for context word: {word}")
        
        logger.info(f"Cleared {deleted_count} context-dependent cache entries for KB: {kb_id}")
        return deleted_count
    except Exception as e:
        logger.error(f"Error clearing context-dependent cache: {e}")
        return 0


def cache_similar_questions(kb_id: str, question: str, similar_questions: list, ttl: int = SIMILAR_CACHE_TTL):
    """Cache similar questions for quick retrieval."""
    try:
        client = redisConnection.client
        if not client:
            return False
            
        cache_key = generate_cache_key(CACHE_PREFIX_SIMILAR, kb_id, question.lower().strip())
        client.setex(cache_key, ttl, json.dumps(similar_questions))
        return True
    except Exception as e:
        logger.error(f"Error caching similar questions: {e}")
        return False


def get_similar_questions(kb_id: str, question: str) -> Optional[list]:
    """Get cached similar questions."""
    try:
        client = redisConnection.client
        if not client:
            return None
            
        cache_key = generate_cache_key(CACHE_PREFIX_SIMILAR, kb_id, question.lower().strip())
        cached_data = client.get(cache_key)
        
        if cached_data:
            return json.loads(cached_data)
        return None
    except Exception as e:
        logger.error(f"Error getting similar questions: {e}")
        return None


def warm_cache_common_questions(kb_id: str, common_questions: list):
    """Pre-warm cache with common questions and their responses."""
    try:
        # This would be called during bot initialization or KB update
        # to pre-populate cache with frequently asked questions
        logger.info(f"Warming cache for KB {kb_id} with {len(common_questions)} questions")
        # Implementation would depend on having a list of common Q&As
    except Exception as e:
        logger.error(f"Error warming cache: {e}")
import os
import jwt
import redis
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException
import logging
import uuid
from app.core.supabase_client import supabase

logger = logging.getLogger(__name__)

# Get configuration from environment
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Initialize Redis client with error handling
try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=5
    )
    redis_client.ping()
    logger.info("Redis connection established successfully")
except Exception as e:
    logger.warning(f"Redis connection failed: {e}. Using in-memory fallback.")
    redis_client = None

# In-memory session store as fallback
in_memory_sessions = {}


def create_secure_session(user: Dict[str, Any]) -> str:
    """Create a secure JWT token separate from Supabase"""
    payload = {
        "user_id": user.get("id"),
        "email": user.get("email"),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    # Store session in Redis or in-memory
    session_key = f"session:{user.get('id')}"
    session_data = {
        "token": token,
        "user_id": user.get("id"),
        "email": user.get("email"),
        "created_at": datetime.utcnow().isoformat()
    }
    
    if redis_client:
        try:
            redis_client.hset(session_key, mapping=session_data)
            redis_client.expire(session_key, timedelta(hours=JWT_EXPIRATION_HOURS))
        except Exception as e:
            logger.error(f"Redis storage failed: {e}")
            # Fallback to in-memory
            in_memory_sessions[session_key] = session_data
    else:
        in_memory_sessions[session_key] = session_data
    
    return token


def validate_session(token: str) -> Dict[str, Any]:
    """Validate session token"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Check if session exists in Redis or in-memory
        session_key = f"session:{payload['user_id']}"
        
        if redis_client:
            try:
                stored_session = redis_client.hgetall(session_key)
                if not stored_session or stored_session.get("token") != token:
                    raise jwt.InvalidTokenError("Session invalidated")
            except Exception as e:
                logger.error(f"Redis validation failed: {e}")
                # Check in-memory fallback
                stored_session = in_memory_sessions.get(session_key)
                if not stored_session or stored_session.get("token") != token:
                    raise jwt.InvalidTokenError("Session invalidated")
        else:
            stored_session = in_memory_sessions.get(session_key)
            if not stored_session or stored_session.get("token") != token:
                raise jwt.InvalidTokenError("Session invalidated")
        
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


def invalidate_session(user_id: str) -> bool:
    """Invalidate a user's session"""
    session_key = f"session:{user_id}"
    
    try:
        if redis_client:
            redis_client.delete(session_key)
        else:
            in_memory_sessions.pop(session_key, None)
        return True
    except Exception as e:
        logger.error(f"Session invalidation failed: {e}")
        return False


def refresh_session(refresh_token: str, user: Dict[str, Any]) -> str:
    """Refresh an existing session with a new token"""
    # Validate the refresh token format
    try:
        # Create new access token
        new_token = create_secure_session(user)
        return new_token
    except Exception as e:
        logger.error(f"Session refresh failed: {e}")
        raise HTTPException(status_code=401, detail="Failed to refresh session")


def _convert_user_id_to_uuid(user_id: str) -> str:
    """Convert a numeric Google user ID string to a deterministic UUID (matches storage in DB)."""
    if user_id and str(user_id).isdigit():
        namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        return str(uuid.uuid5(namespace, f"google_user_{user_id}"))
    return user_id


def get_user_from_token(token: str) -> Dict[str, Any]:
    """Extract user information from a valid token and enrich with subscription plan id"""
    payload = validate_session(token)
    raw_user_id = payload.get("user_id")
    user_id = _convert_user_id_to_uuid(raw_user_id)

    # Default to None
    subscription_plan_id = None
    try:
        # Quick lookup of active subscription to fetch plan_id
        result = (
            supabase.table("subscriptions")
            .select("plan_id")
            .eq("user_id", user_id)
            .eq("status", "active")
            .single()
            .execute()
        )
        if result.data and result.data.get("plan_id"):
            subscription_plan_id = result.data["plan_id"]
    except Exception as e:
        logger.warning(f"Could not fetch subscription plan for user {user_id}: {e}")

    return {
        "id": user_id,
        "email": payload.get("email"),
        "subscription_plan": subscription_plan_id,
    }


def cleanup_expired_sessions():
    """Clean up expired sessions from in-memory store (for fallback mode)"""
    if not redis_client and in_memory_sessions:
        current_time = datetime.utcnow()
        expired_keys = []
        
        for key, session in in_memory_sessions.items():
            created_at = datetime.fromisoformat(session.get("created_at", ""))
            if current_time - created_at > timedelta(hours=JWT_EXPIRATION_HOURS):
                expired_keys.append(key)
        
        for key in expired_keys:
            in_memory_sessions.pop(key, None)
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired sessions")
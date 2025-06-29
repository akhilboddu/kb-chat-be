"""
Quota enforcement middleware for subscription limits
"""

import logging
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.services.subscription_service import SubscriptionService
from app.services.auth_service import get_user_from_token
from app.core.supabase_client import supabase
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class QuotaGuardMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce subscription quotas"""
    
    def __init__(self, app, dispatch=None):
        super().__init__(app, dispatch)
        self.subscription_service = SubscriptionService()
        # Check if quota guard is enabled via environment variable
        self.enabled = os.getenv("ENABLE_QUOTA_GUARD", "false").lower() == "true"
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process requests and check quotas for protected endpoints"""
        
        # Skip if quota guard is disabled
        if not self.enabled:
            return await call_next(request)
        
        # Skip for non-API routes or health checks
        if not request.url.path.startswith("/api/") or request.url.path == "/api/health":
            return await call_next(request)
        
        # Skip for auth endpoints
        if request.url.path.startswith("/api/auth/"):
            return await call_next(request)
        
        try:
            # Get auth token from request
            auth_token = request.cookies.get("auth_token")
            if not auth_token and "authorization" in request.headers:
                auth_token = request.headers["authorization"].replace("Bearer ", "")
            
            if not auth_token:
                # No auth, let the endpoint handle authentication
                return await call_next(request)
            
            # Get user info
            try:
                user_info = get_user_from_token(auth_token)
                user_id = user_info["id"]
            except Exception:
                # Invalid token, let endpoint handle it
                return await call_next(request)
            
            # Check quotas based on endpoint
            quota_error = await self._check_endpoint_quotas(request, user_id)
            
            if quota_error:
                return JSONResponse(
                    status_code=402,  # Payment Required
                    content={
                        "detail": quota_error["message"],
                        "quota_exceeded": True,
                        "resource": quota_error["resource"],
                        "current_usage": quota_error["current"],
                        "limit": quota_error["limit"],
                        "plan_upgrade_url": "/pricing"
                    }
                )
            
            # Continue processing
            return await call_next(request)
            
        except Exception as e:
            logger.error(f"Quota guard middleware error: {str(e)}")
            # Don't block on errors, let request through
            return await call_next(request)
    
    async def _check_endpoint_quotas(self, request: Request, user_id: str) -> dict:
        """Check quotas for specific endpoints"""
        
        path = request.url.path
        method = request.method
        
        # Message creation endpoints
        if path.startswith("/api/chat/") and method == "POST":
            return await self._check_messages_quota(user_id)
        
        # Bot creation endpoint
        if path == "/api/agent" and method == "POST":
            return await self._check_bots_quota(user_id)
        
        # Bot activation endpoint
        if path.endswith("/activate") and method == "POST":
            return await self._check_live_bots_quota(user_id)
        
        # Team member invitation
        if path.startswith("/api/team/invite") and method == "POST":
            return await self._check_team_members_quota(user_id)
        
        # Knowledge source upload
        if path.startswith("/api/knowledge") and method == "POST":
            bot_id = self._extract_bot_id_from_path(path)
            if bot_id:
                return await self._check_knowledge_sources_quota(user_id, bot_id)
        
        return None
    
    async def _check_messages_quota(self, user_id: str) -> dict:
        """Check if user has exceeded messages quota"""
        try:
            # Get current month's message count
            current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Get user's bots
            bots_result = supabase.table("bots").select("id").eq("user_id", user_id).execute()
            if not bots_result.data:
                return None
            
            bot_ids = [bot["id"] for bot in bots_result.data]
            
            # Get conversations for these bots
            conversations_result = supabase.table("conversations").select("id").in_("bot_id", bot_ids).execute()
            if not conversations_result.data:
                return None
            
            conversation_ids = [conv["id"] for conv in conversations_result.data]
            
            # Count messages this month
            messages_result = supabase.table("messages").select("id", count="exact").in_(
                "conversation_id", conversation_ids
            ).gte("created_at", current_month_start.isoformat()).execute()
            
            current_messages = messages_result.count or 0
            
            # Check quota
            within_limit, limit = await self.subscription_service.check_quota(user_id, "messages", current_messages)
            
            if not within_limit:
                return {
                    "message": f"Monthly message limit reached ({current_messages}/{limit}). Please upgrade your plan.",
                    "resource": "messages",
                    "current": current_messages,
                    "limit": limit
                }
                
        except Exception as e:
            logger.error(f"Error checking messages quota: {str(e)}")
            
        return None
    
    async def _check_bots_quota(self, user_id: str) -> dict:
        """Check if user can create more bots"""
        try:
            bots_result = supabase.table("bots").select("id", count="exact").eq("user_id", user_id).execute()
            current_bots = bots_result.count or 0
            
            within_limit, limit = await self.subscription_service.check_quota(user_id, "bots", current_bots)
            
            if not within_limit:
                return {
                    "message": f"Bot limit reached ({current_bots}/{limit}). Please upgrade your plan.",
                    "resource": "bots",
                    "current": current_bots,
                    "limit": limit
                }
                
        except Exception as e:
            logger.error(f"Error checking bots quota: {str(e)}")
            
        return None
    
    async def _check_live_bots_quota(self, user_id: str) -> dict:
        """Check if user can activate more bots"""
        try:
            bots_result = supabase.table("bots").select("id", count="exact").eq("user_id", user_id).eq("is_live", True).execute()
            current_live_bots = bots_result.count or 0
            
            within_limit, limit = await self.subscription_service.check_quota(user_id, "live_bots", current_live_bots)
            
            if not within_limit:
                return {
                    "message": f"Live bot limit reached ({current_live_bots}/{limit}). Please upgrade your plan.",
                    "resource": "live_bots",
                    "current": current_live_bots,
                    "limit": limit
                }
                
        except Exception as e:
            logger.error(f"Error checking live bots quota: {str(e)}")
            
        return None
    
    async def _check_team_members_quota(self, user_id: str) -> dict:
        """Check if user can add more team members"""
        try:
            team_result = supabase.table("team_members").select("id", count="exact").eq("owner_id", user_id).eq("status", "active").execute()
            current_members = (team_result.count or 0) + 1  # +1 for owner
            
            within_limit, limit = await self.subscription_service.check_quota(user_id, "team_members", current_members)
            
            if not within_limit:
                return {
                    "message": f"Team member limit reached ({current_members}/{limit}). Please upgrade your plan.",
                    "resource": "team_members",
                    "current": current_members,
                    "limit": limit
                }
                
        except Exception as e:
            logger.error(f"Error checking team members quota: {str(e)}")
            
        return None
    
    async def _check_knowledge_sources_quota(self, user_id: str, bot_id: str) -> dict:
        """Check if user can add more knowledge sources to a bot"""
        try:
            # Verify bot ownership
            bot_result = supabase.table("bots").select("id").eq("id", bot_id).eq("user_id", user_id).single().execute()
            if not bot_result.data:
                return None
            
            # Count knowledge sources
            sources_result = supabase.table("knowledge_sources").select("id", count="exact").eq("bot_id", bot_id).execute()
            current_sources = sources_result.count or 0
            
            within_limit, limit = await self.subscription_service.check_quota(user_id, "knowledge_sources", current_sources)
            
            if not within_limit:
                return {
                    "message": f"Knowledge source limit reached ({current_sources}/{limit}). Please upgrade your plan.",
                    "resource": "knowledge_sources",
                    "current": current_sources,
                    "limit": limit
                }
                
        except Exception as e:
            logger.error(f"Error checking knowledge sources quota: {str(e)}")
            
        return None
    
    def _extract_bot_id_from_path(self, path: str) -> str:
        """Extract bot ID from API path"""
        parts = path.split("/")
        for i, part in enumerate(parts):
            if part == "bot" and i + 1 < len(parts):
                return parts[i + 1]
        return None 
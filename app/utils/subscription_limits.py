"""Utility helpers for enforcing subscription-based usage limits.

NOTE 2025-06-29 – This module used to duplicate the logic that already
exists in ``SubscriptionService``.  To enforce a *single* source of truth,
all limit retrieval is now delegated to ``SubscriptionService`` which, in
turn, reads the authoritative ``plans`` table in Supabase.
"""

from typing import Dict, Any, Optional, Tuple
from fastapi import HTTPException
from app.core.supabase_client import supabase
from app.utils.logging import get_logger
from app.services.subscription_service import SubscriptionService
from app.config.subscription_limits import get_plan_limits, SUBSCRIPTION_LIMITS
from datetime import datetime, timezone

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Single source of truth helper
# ---------------------------------------------------------------------------

_subscription_service = SubscriptionService()

def _get_limits_for_user(user_id: str) -> Dict[str, Any]:
    """Wrapper around ``SubscriptionService.get_plan_limits`` that converts
    the returned ``PlanLimits`` pydantic model into a plain dictionary usable
    inside this legacy helper module.
    """

    limits_obj = _subscription_service.get_plan_limits(user_id)
    return limits_obj.dict() if hasattr(limits_obj, "dict") else dict(limits_obj)

async def get_bot_and_user(bot_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch bot and user info from Supabase.
    Returns bot row with user_id, and user row with payment_status.
    """
    try:
        bot_resp = supabase.table("bots").select("*").eq("id", bot_id).single().execute()
        if not bot_resp.data:
            logger.error(f"Bot not found: {bot_id}")
            return None
        bot_data = bot_resp.data
        user_id = bot_data.get("user_id")
        if not user_id:
            logger.error(f"No user_id found for bot: {bot_id}")
            return None
        user_resp = supabase.table("subscriptions").select("*").eq("user_id", user_id).execute()
        print(f"user_resp: {user_resp}")
        if not user_resp.data:
            logger.warning(f"No subscription found for user: {user_id}, using TRIAL defaults")
            # Create default trial subscription data
            user_data = {
                "user_id": user_id,
                "plan_name": "trial", 
                "status": "active"
            }
        else:
            # Fix: user_resp.data is a LIST, get the first item
            user_data = user_resp.data[0] if user_resp.data else {
                "user_id": user_id,
                "plan_name": "trial", 
                "status": "active"
            }
        return {"bot": bot_data, "user": user_data}
    except Exception as e:
        logger.error(f"Error fetching bot/user: {str(e)}")
        return None

async def get_message_count(user_id: str, start_date: str) -> int:
    try:
        # Normalise simple ISO strings so PostgREST understands them.  We
        # keep the original precision and the ":" in the UTC offset.
        if start_date:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                # Re-emit using builtin isoformat() which yields the canonical
                # form "YYYY-MM-DDTHH:MM:SS.ssssss+00:00".
                start_date = dt.isoformat()
            except Exception:
                # Leave start_date untouched on failure – better to run the
                # filter unmodified than to create an invalid timestamp string
                pass
        
        # Get all bot IDs for this user
        bots_resp = supabase.table("bots").select("id").eq("user_id", user_id).execute()
        bot_ids = [b["id"] for b in bots_resp.data] if bots_resp.data else []
        if not bot_ids:
            return 0
        # Get all conversations for these bots (no date filter – we want messages in *any* conversation)
        convs_resp = supabase.table("conversations").select("id").in_("bot_id", bot_ids).execute()
        conv_ids = [c["id"] for c in convs_resp.data] if convs_resp.data else []
        if not conv_ids:
            return 0
        # Count messages in these conversations
        msgs_resp = (
            supabase.table("messages")
            .select("id", count="exact")
            .in_("conversation_id", conv_ids)
            .gte("created_at", start_date)  # Only messages created *this* month
            .execute()
        )
        # supabase-py sets .count only when server sends Content-Range header.
        # On some PostgREST setups that header is omitted; fall back to len(data).
        if msgs_resp.count is not None:
            return msgs_resp.count
        return len(msgs_resp.data or [])
    except Exception as e:
        logger.error(f"Error getting message count: {str(e)}")
        return 0

async def get_conversation_count(user_id: str, start_date: str) -> int:
    try:
        # Normalise simple ISO strings so PostgREST understands them.  We
        # keep the original precision and the ":" in the UTC offset.
        if start_date:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                # Re-emit using builtin isoformat() which yields the canonical
                # form "YYYY-MM-DDTHH:MM:SS.ssssss+00:00".
                start_date = dt.isoformat()
            except Exception:
                # Leave start_date untouched on failure – better to run the
                # filter unmodified than to create an invalid timestamp string
                pass
        
        bots_resp = supabase.table("bots").select("id").eq("user_id", user_id).execute()
        bot_ids = [b["id"] for b in bots_resp.data] if bots_resp.data else []
        if not bot_ids:
            return 0
        convs_resp = supabase.table("conversations").select("id", count="exact").in_("bot_id", bot_ids).gte("created_at", start_date).execute()
        # supabase-py sets .count only when server sends Content-Range header.
        # On some PostgREST setups that header is omitted; fall back to len(data).
        if convs_resp.count is not None:
            return convs_resp.count
        return len(convs_resp.data or [])
    except Exception as e:
        logger.error(f"Error getting conversation count: {str(e)}")
        return 0

async def check_subscription_limits(bot_id: str, conversation_id: str) -> Tuple[bool, Optional[str]]:
    """
    Check if the user has reached their subscription limits.
    Args:
        bot_id: The ID of the bot
        conversation_id: The ID of the conversation
    Returns:
        Tuple[bool, Optional[str]]: 
            - True if limits are exceeded, False otherwise
            - Error message if limits are exceeded, None otherwise
    """
    try:
        # Get bot and user info
        info = await get_bot_and_user(bot_id)
        logger.debug(f"Subscription limits – bot/user info: {info}")

        if not info:
            return True, "Bot or user not found"

        user_id = info["bot"].get("user_id")

        # Fetch authoritative limits for this *user* (plan is inferred from
        # their active subscription).  This guarantees we hit the single
        # source of truth (plans table) via SubscriptionService.
        limits = _get_limits_for_user(user_id)

        logger.debug(f"Authoritative plan limits for user {user_id}: {limits}")
        # --- MONTHLY LIMITS LOGIC ---
        # Only count messages/conversations from the 1st of the current month (UTC) to now
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        # Get message count for current month
        message_count = await get_message_count(user_id, start_of_month.isoformat())
        # Get conversation count for current month
        conversation_count = await get_conversation_count(user_id, start_of_month.isoformat())
        # The PlanLimits model uses camel-case keys (maxMessages, …)
        # Convert to lower snake for backwards-compat readability.
        trial_limits = get_plan_limits("TRIAL")
        max_messages = limits.get("maxMessages", trial_limits["maxMessages"])
        max_conversations = limits.get("maxConversations", trial_limits["maxConversations"])

        # Check message limit
        if message_count >= int(max_messages):
            return True, (
                f"You have reached your monthly message limit of {max_messages} "
                "messages. Please upgrade your subscription to continue."
            )

        # Check conversation limit
        if conversation_count >= int(max_conversations):
            return True, (
                f"You have reached your monthly conversation limit of {max_conversations} "
                "conversations. Please upgrade your subscription to continue."
            )
        return False, None
    except Exception as e:
        logger.error(f"Error checking subscription limits: {str(e)}")
        return True, "Error checking subscription limits"

async def enforce_subscription_limits(bot_id: str, conversation_id: str) -> None:
    """
    Enforce subscription limits by raising an HTTPException if limits are exceeded.
    Args:
        bot_id: The ID of the bot
        conversation_id: The ID of the conversation
    Raises:
        HTTPException: If subscription limits are exceeded
    """
    # Skip limits check for preview conversations
    if conversation_id.startswith("preview_"):
        return
        
    limit_exceeded, error_message = await check_subscription_limits(bot_id, conversation_id)
    if limit_exceeded:
        logger.debug(f"Subscription limit exceeded? {limit_exceeded}")
        raise HTTPException(
            status_code=403,
            detail=error_message or "Subscription limit exceeded"
        ) 
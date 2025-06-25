from typing import Dict, Any, Optional, Tuple
from fastapi import HTTPException
from app.core.supabase_client import supabase
from app.utils.logging import get_logger
from datetime import datetime, timezone

logger = get_logger(__name__)

async def get_plan_limits(plan_name: str) -> Dict[str, Any]:
    """
    Fetch plan limits from the 'plans' table in Supabase.
    Args:
        plan_name: The name of the plan (e.g., "Trial", "STARTER", "Pro", "Enterprise")
    Returns:
        Dict containing the plan limits
    """
    try:
        plan_name_norm = plan_name
        print(f"THIS IS THE PLAN NAME NORM: {plan_name_norm}")
        response = supabase.table("plans").select("*").execute()
        if not response.data:
            logger.warning(f"No plans found in table, using default limits")
            return {"messages": 100, "conversations": 20, "live_bots": 1}
        for plan in response.data:
            if plan.get("name", "") == plan_name_norm:
                return plan
        logger.warning(f"Plan '{plan_name}' not found, using default limits")
        return {"messages": 100, "conversations": 20, "live_bots": 1}
    except Exception as e:
        logger.error(f"Error fetching plan limits: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching subscription limits")

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
        # Get all bot IDs for this user
        bots_resp = supabase.table("bots").select("id").eq("user_id", user_id).execute()
        bot_ids = [b["id"] for b in bots_resp.data] if bots_resp.data else []
        if not bot_ids:
            return 0
        # Get all conversations for these bots
        convs_resp = supabase.table("conversations").select("id").in_("bot_id", bot_ids).gte("created_at", start_date).execute()
        conv_ids = [c["id"] for c in convs_resp.data] if convs_resp.data else []
        if not conv_ids:
            return 0
        # Count messages in these conversations
        msgs_resp = supabase.table("messages").select("id", count="exact").in_("conversation_id", conv_ids).execute()
        return msgs_resp.count or 0
    except Exception as e:
        logger.error(f"Error getting message count: {str(e)}")
        return 0

async def get_conversation_count(user_id: str, start_date: str) -> int:
    try:
        bots_resp = supabase.table("bots").select("id").eq("user_id", user_id).execute()
        bot_ids = [b["id"] for b in bots_resp.data] if bots_resp.data else []
        if not bot_ids:
            return 0
        convs_resp = supabase.table("conversations").select("id", count="exact").in_("bot_id", bot_ids).gte("created_at", start_date).execute()
        return convs_resp.count or 0
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
        print(f"info: {info}")
        if not info:
            return True, "Bot or user not found"
        user_id = info["bot"].get("user_id")
        user_profile = info["user"]
        subscription_tier = user_profile.get("plan_name", "Trial")
        print(f"THIS IS THE SUBSCRIPTION TIER: {subscription_tier}")
        # Get plan limits from database
        limits = await get_plan_limits(subscription_tier)
        print(f"THIS IS THE LIMITS: {limits}")
        # --- MONTHLY LIMITS LOGIC ---
        # Only count messages/conversations from the 1st of the current month (UTC) to now
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        # Get message count for current month
        message_count = await get_message_count(user_id, start_of_month.isoformat())
        # Get conversation count for current month
        conversation_count = await get_conversation_count(user_id, start_of_month.isoformat())
        # Check message limit
        if message_count >= int(limits.get("messages", 100)):
            return True, f"You have reached your monthly message limit of {limits.get('messages', 100)} messages. Please upgrade your subscription to continue."
        # Check conversation limit
        if conversation_count >= int(limits.get("conversations", 20)):
            return True, f"You have reached your monthly conversation limit of {limits.get('conversations', 20)} conversations. Please upgrade your subscription to continue."
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
    limit_exceeded, error_message = await check_subscription_limits(bot_id, conversation_id)
    if limit_exceeded:
        print(f"limit_exceeded: {limit_exceeded}")
        raise HTTPException(
            status_code=403,
            detail=error_message or "Subscription limit exceeded"
        ) 
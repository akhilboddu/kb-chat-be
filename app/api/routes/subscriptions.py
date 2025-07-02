from fastapi import APIRouter, HTTPException, Request
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict

from app.core.supabase_client import supabase
from app.models.subscription import SubscriptionResponse, BotResponse, DashboardStatsResponse, SubscriptionOut
from app.services.auth_service import get_user_from_token
from app.services.subscription_service import SubscriptionService
from app.utils.subscription_limits import get_message_count, get_conversation_count  # noqa: E501

logger = logging.getLogger(__name__)
subscriptions_router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def convert_user_id_to_uuid(user_id: str) -> str:
    """Convert Google OAuth user ID to deterministic UUID for database compatibility"""
    if user_id.isdigit():  # Google user ID (numeric string)
        # Create a deterministic UUID from the Google user ID
        namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # DNS namespace
        user_uuid = str(uuid.uuid5(namespace, f"google_user_{user_id}"))
        logger.debug(f"Converting Google user ID {user_id} to UUID: {user_uuid}")
        return user_uuid
    else:
        return user_id  # Already a UUID


@subscriptions_router.get("/info", response_model=SubscriptionOut)
async def get_subscription_info(request: Request):
    """Return the caller's active subscription **including** the full Plan object so the
    frontend can read ``subscription.plan.limits`` without an extra round-trip.

    This is now delegated to ``SubscriptionService.get_subscription_with_plan``
    which in turn reads the authoritative ``plans`` table.  It therefore keeps
    plan-limit logic in a single place (and in sync with QuotaGuard).
    """
    try:
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        if not auth_token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Validate token and get user info
        user_info = get_user_from_token(auth_token)
        user_id = user_info["id"]
        user_uuid = convert_user_id_to_uuid(user_id)
        
        logger.info(f"📊 Subscription info request for user {user_id} (UUID: {user_uuid})")

        subscription_service = SubscriptionService()
        subscription = subscription_service.get_subscription_with_plan(user_uuid)

        if subscription:
            if subscription.plan is None and subscription.plan_id:
                # Join failed; fetch plan row manually to attach limits
                plan_resp = supabase.table("plans").select("*").eq("id", subscription.plan_id).single().execute()
                if plan_resp.data:
                    plan_data = plan_resp.data
                    if not plan_data.get("limits"):
                        plan_data["limits"] = {
                            "maxMessages": plan_data.get("messages", 50),
                            "maxConversations": plan_data.get("conversations", 10),
                            "maxBots": plan_data.get("live_bots", 1) * 3,
                            "maxLiveBots": plan_data.get("live_bots", 1),
                            "maxKnowledgeSources": 10,
                            "maxTeamMembers": plan_data.get("team_members", 1),
                        }
                    subscription.plan = Plan(
                        id=plan_data["id"],
                        key=plan_data.get("key", "TRIAL"),
                        name=plan_data.get("name", "Trial"),
                        price_cents=plan_data.get("price_cents", 0),
                        currency=plan_data.get("currency", "usd"),
                        limits=PlanLimits(**plan_data["limits"]),
                        features=plan_data.get("features", {}),
                        is_active=plan_data.get("is_active", True),
                    )
            logger.info(f"📊 Returning subscription with plan {subscription.plan.key if subscription.plan else 'UNKNOWN'}")
            return subscription

        # No active sub – fabricate a TRIAL SubscriptionOut using service limits
        trial_limits = subscription_service.get_plan_limits(user_uuid)

        trial_plan = {
            "id": "trial-plan",
            "key": "TRIAL",
            "name": "deskForce Trial Plan",
            "price_cents": 0,
            "currency": "usd",
            "limits": trial_limits.dict(),
            "features": {},
            "is_active": True,
        }

        trial_subscription = SubscriptionOut(
            id="trial",
            user_id=user_uuid,
            plan_name="deskForce Trial Plan",
            plan_id=None,
            plan=trial_plan,  # embeds limits
            price=0.0,
            billing_cycle="monthly",
            status="active",
            start_date=datetime.utcnow(),
            end_date=None,
            auto_renew=False,
            created_at=datetime.utcnow(),
        )

        return trial_subscription
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Subscription info error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


async def get_active_conversations_per_bot(user_uuid: str) -> Dict[str, int]:
    """Get active conversation count for each bot owned by the user."""
    try:
        # Get all bots for the user
        bots_resp = supabase.table("bots").select("id").eq("user_id", user_uuid).execute()
        if not bots_resp.data:
            return {}
        
        bot_ids = [bot["id"] for bot in bots_resp.data]
        
        # Get active conversations for all bots (status != 'closed')
        conversations_resp = (
            supabase.table("conversations")
            .select("bot_id")
            .in_("bot_id", bot_ids)
            .neq("status", "closed")
            .execute()
        )
        
        # Count conversations per bot
        active_counts = {}
        for conv in conversations_resp.data or []:
            bot_id = conv["bot_id"]
            active_counts[bot_id] = active_counts.get(bot_id, 0) + 1
        
        return active_counts
    except Exception as e:
        logger.error(f"Error getting active conversations per bot: {e}")
        return {}


@subscriptions_router.get("/dashboard-stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(request: Request):
    """Get dashboard stats - SIMPLIFIED to just pull from database"""
    try:
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        if not auth_token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Validate token and get user info
        user_info = get_user_from_token(auth_token)
        user_id = user_info["id"]
        user_uuid = convert_user_id_to_uuid(user_id)
        token_plan_id = user_info.get("subscription_plan")
        
        # Validate token_plan_id exists in plans table
        valid_token_plan = None
        if token_plan_id:
            check = supabase.table("plans").select("id").eq("id", token_plan_id).single().execute()
            if check.data:
                valid_token_plan = token_plan_id
        
        logger.info(f"📊 Dashboard stats for user: {user_id} (UUID: {user_uuid})")
        
        # Two separate queries since join isn't working
        # 1. Get subscription
        subscription_result = supabase.table("subscriptions").select("*").eq("user_id", user_uuid).eq("status", "active").execute()
        
        if not subscription_result.data:
            logger.warning(f"No active subscription found for user {user_uuid}. Returning default trial subscription")
            # Default trial limits
            default_limits = {
                "maxMessages": 50,
                "maxConversations": 10,
                "maxBots": 1,
                "maxLiveBots": 1,
                "maxKnowledgeSources": 2,
                "maxTeamMembers": 1,
            }
            # Get bots for trial user too
            bots_resp = supabase.table("bots").select("*").eq("user_id", user_uuid).execute()
            bots_list = bots_resp.data if bots_resp.data else []
            
            # Get active conversations per bot for trial user
            active_conversations_per_bot = await get_active_conversations_per_bot(user_uuid)
            
            # Add active_conversations to each bot
            for bot in bots_list:
                bot["active_conversations"] = active_conversations_per_bot.get(bot["id"], 0)
            
            # Calculate total active conversations
            total_active_conversations = sum(active_conversations_per_bot.values())
            
            # Build trial response with real bot data
            trial_stats = DashboardStatsResponse(
                total_messages=0,
                total_conversations=0,
                active_conversations=total_active_conversations,
                team_member_count=1,
                subscription=SubscriptionResponse(
                    id="trial",
                    user_id=user_uuid,
                    plan_id=None,
                    plan_name="deskForce Trial Plan",
                    status="active",
                    price=0.0,
                    billing_cycle="monthly",
                    start_date=datetime.utcnow(),
                    auto_renew=False,
                    created_at=datetime.utcnow(),
                ),
                plan_limits=default_limits,
                bots=bots_list,
            )
            return trial_stats
        
        sub_data = subscription_result.data[0]
        plan_id = sub_data["plan_id"]
        
        # 2. Get plan data (prefer plan_id from token if available)
        effective_plan_id = valid_token_plan or plan_id
        plan_result = supabase.table("plans").select("*").eq("id", effective_plan_id).execute()
        
        if not plan_result.data:
            logger.warning(f"No plan found for ID {effective_plan_id}. Falling back to inferred limits")
            subscription_service = SubscriptionService()
            inferred_limits = subscription_service.get_plan_limits(user_uuid)
            plan_data = {
                "key": sub_data.get("plan_name", "TRIAL").split()[1].upper() if sub_data.get("plan_name") else "TRIAL",
                "name": sub_data.get("plan_name", "Trial"),
                "limits": inferred_limits.dict() if hasattr(inferred_limits, 'dict') else inferred_limits,
            }
        else:
            plan_data = plan_result.data[0]
        
        logger.info(f"✅ Found plan: {plan_data['key']} with limits: {plan_data['limits']}")
        
        # --- Usage calculations ---
        # Get start of the current month (UTC)
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Calculate usage metrics
        total_messages = await get_message_count(user_uuid, start_of_month.isoformat())
        total_conversations = await get_conversation_count(user_uuid, start_of_month.isoformat())

        # Fetch bots for the user (needed for live bot counts & dashboard listing)
        bots_resp = supabase.table("bots").select("*").eq("user_id", user_uuid).execute()
        bots_list = bots_resp.data if bots_resp.data else []

        live_bot_count = len([b for b in bots_list if b.get("is_live")])
        
        # Get active conversations per bot
        active_conversations_per_bot = await get_active_conversations_per_bot(user_uuid)
        
        # Add active_conversations to each bot
        for bot in bots_list:
            bot["active_conversations"] = active_conversations_per_bot.get(bot["id"], 0)
        
        # Calculate total active conversations
        total_active_conversations = sum(active_conversations_per_bot.values())

        # Build response with real usage data
        stats = DashboardStatsResponse(
            total_messages=total_messages,
            total_conversations=total_conversations,
            active_conversations=total_active_conversations,
            team_member_count=1,  # TODO: Replace with real team member count when table ready
            subscription=SubscriptionResponse(
                id=sub_data["id"],
                user_id=sub_data["user_id"],
                plan_id=effective_plan_id,
                plan_name=sub_data["plan_name"],
                status=sub_data["status"],
                price=sub_data.get("price", 0.0),
                billing_cycle=sub_data.get("billing_cycle", "monthly"),
                start_date=datetime.fromisoformat(sub_data["created_at"].replace('Z', '+00:00')),
                end_date=None,
                auto_renew=False,
                created_at=datetime.fromisoformat(sub_data["created_at"].replace('Z', '+00:00'))
            ),
            plan_limits=plan_data["limits"],  # Limits fetched from plans table
            bots=bots_list  # Pass the full bots list for frontend rendering
        )
        
        logger.info(
            f"📊 Returning dashboard stats: messages={total_messages}, conversations={total_conversations}, plan={plan_data.get('key')}"
        )
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dashboard stats error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

from fastapi import APIRouter, HTTPException, Request
import logging
import uuid
from datetime import datetime, timedelta

from app.core.supabase_client import supabase
from app.models.subscription import SubscriptionResponse, BotResponse, DashboardStatsResponse
from app.services.auth_service import get_user_from_token

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


@subscriptions_router.get("/info", response_model=SubscriptionResponse)
async def get_subscription_info(request: Request):
    """Get current user's active subscription using auth token from cookies"""
    try:
        logger.info("=== SUBSCRIPTION INFO ENDPOINT CALLED ===")
        
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        logger.info(f"Auth token present: {bool(auth_token)}")
        logger.info(f"Auth token length: {len(auth_token) if auth_token else 0}")
        logger.info(f"Request cookies: {list(request.cookies.keys())}")
        
        if not auth_token:
            logger.error("No auth token found in request cookies")
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Validate token and get user info
        logger.info("Validating auth token...")
        try:
            user_info = get_user_from_token(auth_token)
            logger.info(f"Auth token validation successful")
            logger.info(f"User info keys: {list(user_info.keys()) if user_info else 'None'}")
        except Exception as auth_error:
            logger.error(f"Auth token validation failed: {str(auth_error)}")
            logger.error(f"Auth error type: {type(auth_error)}")
            raise HTTPException(status_code=401, detail=f"Authentication failed: {str(auth_error)}")
        
        user_id = user_info["id"]
        logger.info(f"Original user ID: {user_id}")
        logger.info(f"User ID type: {type(user_id)}")
        logger.info(f"User ID is digit: {str(user_id).isdigit()}")
        
        # Convert user_id to UUID for database compatibility (Google OAuth compatibility)
        user_uuid = convert_user_id_to_uuid(user_id)
        logger.info(f"Converted user UUID: {user_uuid}")
        logger.info(f"UUID type: {type(user_uuid)}")
        
        # Query subscriptions table using Supabase service role
        logger.info("Querying subscriptions table...")
        logger.info(f"Query: subscriptions.select(*).eq('user_id', '{user_uuid}').eq('status', 'active')")
        
        try:
            result = supabase.table("subscriptions").select("*").eq("user_id", user_uuid).eq("status", "active").order("created_at", desc=True).limit(1).execute()
            logger.info(f"Supabase query executed successfully")
            logger.info(f"Result type: {type(result)}")
            logger.info(f"Result has data: {hasattr(result, 'data')}")
            logger.info(f"Result has error: {hasattr(result, 'error')}")
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"Supabase query error: {result.error}")
                logger.error(f"Error type: {type(result.error)}")
                raise HTTPException(status_code=500, detail=f"Database query failed: {result.error}")
            
            if hasattr(result, 'data'):
                logger.info(f"Query returned {len(result.data) if result.data else 0} results")
                logger.info(f"Data: {result.data}")
            else:
                logger.error("Result object missing 'data' attribute")
                raise HTTPException(status_code=500, detail="Invalid database response structure")
                
        except Exception as db_error:
            logger.error(f"Database query exception: {str(db_error)}")
            logger.error(f"DB error type: {type(db_error)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(db_error)}")
        
        if not result.data:
            logger.info("No subscription found, returning default free subscription")
            # Return default/free subscription if none found
            from datetime import datetime, timedelta
            now_iso = datetime.utcnow().isoformat()
            default_sub = {
                "id": "free",
                "user_id": user_uuid,
                "plan_name": "free",
                "status": "active",
                "price": 0,
                "billing_cycle": "annual",
                "start_date": now_iso,
                "end_date": None,
                "auto_renew": False,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            logger.info(f"Default subscription payload: {default_sub}")
            return default_sub
        
        subscription_data = result.data[0]
        logger.info(f"Found subscription data: {subscription_data}")
        logger.info(f"Subscription keys: {list(subscription_data.keys())}")
        
        try:
            subscription_response = SubscriptionResponse(**subscription_data)
            logger.info(f"Successfully created SubscriptionResponse")
            logger.info(f"Response: {subscription_response.model_dump()}")
            return subscription_response
        except Exception as response_error:
            logger.error(f"Failed to create SubscriptionResponse: {str(response_error)}")
            logger.error(f"Response error type: {type(response_error)}")
            raise HTTPException(status_code=500, detail=f"Response creation failed: {str(response_error)}")
        
    except HTTPException:
        logger.info("Re-raising HTTPException")
        raise
    except Exception as e:
        logger.error(f"=== UNEXPECTED EXCEPTION IN SUBSCRIPTION INFO ===")
        logger.error(f"Exception type: {type(e)}")
        logger.error(f"Exception message: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        logger.error("=== END SUBSCRIPTION INFO EXCEPTION ===")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@subscriptions_router.get("/dashboard-stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(request: Request):
    """Get all dashboard statistics for authenticated user"""
    try:
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        
        if not auth_token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Validate token and get user info
        user_info = get_user_from_token(auth_token)
        user_id = user_info["id"]
        
        logger.info(f"Fetching dashboard stats for user: {user_id}")
        
        # Initialize response object
        stats = DashboardStatsResponse(
            total_messages=0,
            total_conversations=0,
            active_conversations=0,
            team_member_count=0,
            subscription=None,
            bots=[]
        )
        
        # Fetch user's subscription
        try:
            subscription_result = supabase.table("subscriptions").select("*").eq("user_id", user_id).eq("status", "active").order("created_at", desc=True).limit(1).execute()
            
            if subscription_result.data:
                stats.subscription = SubscriptionResponse(**subscription_result.data[0])
            else:
                # Default free subscription
                stats.subscription = SubscriptionResponse(
                    id="free",
                    user_id=user_id,
                    plan_name="free",
                    status="active"
                )
        except Exception as e:
            logger.warning(f"Could not fetch subscription data: {e}")
        
        # Fetch user's bots
        try:
            # Convert user_id to UUID for database compatibility
            user_uuid = convert_user_id_to_uuid(user_id)
            bots_result = supabase.table("bots").select("*").eq("user_id", user_uuid).execute()
            
            if bots_result.data:
                for bot_data in bots_result.data:
                    # Get active conversations count for each bot
                    conversations_result = supabase.table("conversations").select("id", count="exact").eq("bot_id", bot_data["id"]).eq("status", "active").execute()
                    active_count = conversations_result.count if conversations_result.count else 0
                    
                    bot_data["active_conversations"] = active_count
                    stats.bots.append(BotResponse(**bot_data))
                
                # Calculate totals
                bot_ids = [bot.id for bot in stats.bots]
                
                if bot_ids:
                    # Total messages across all bots
                    messages_result = supabase.table("messages").select("id", count="exact").in_("bot_id", bot_ids).execute()
                    stats.total_messages = messages_result.count if messages_result.count else 0
                    
                    # Total conversations across all bots
                    total_conversations_result = supabase.table("conversations").select("id", count="exact").in_("bot_id", bot_ids).execute()
                    stats.total_conversations = total_conversations_result.count if total_conversations_result.count else 0
                    
                    # Active conversations
                    stats.active_conversations = sum(bot.active_conversations or 0 for bot in stats.bots)
        
        except Exception as e:
            logger.warning(f"Could not fetch bot data: {e}")
        
        # Fetch team member count
        try:
            team_result = supabase.table("team_members").select("id", count="exact").eq("user_id", user_id).execute()
            stats.team_member_count = team_result.count if team_result.count else 0
        except Exception as e:
            logger.warning(f"Could not fetch team member count: {e}")
        
        logger.info(f"Dashboard stats compiled successfully for user {user_id}")
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get dashboard stats exception: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard stats: {str(e)}")

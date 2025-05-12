import json
from fastapi import APIRouter

from app.core.supabase_client import supabase
from app.core.db_manager import PushSub
from app.models.base import StatusResponse


router = APIRouter(prefix="/notifications", tags=["anon_notifications"])


@router.post("/save-subscription", response_model=StatusResponse)
async def save_notification(data: PushSub):
    try:
        print(
            f"Received for save notification for id {data.user_id} and {data.anon_id}"
        )

        subscription_str = json.dumps(data.subscription)

        supabase.table("anon_push_subscriptions").upsert(
            {
                "user_id": data.user_id,
                "anon_id": data.anon_id,
                "subscription": subscription_str,
            },
            on_conflict="anon_id",  # 👈 this is the fix
        ).execute()
        return StatusResponse(
            status="success",
            message="Notification has been registered successfully",
        )
    except Exception as e:
        print(f"Exception while registering notificaiton {e}")
        return StatusResponse(
            status="error",
            message="Notification has not been registered ",
        )

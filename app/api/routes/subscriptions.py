from fastapi import APIRouter, Depends
from realtime import logging

from app.utils.verification import get_current_user


logger = logging.getLogger(__name__)
subscriptions_router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@subscriptions_router.get("/info")
async def get_subscription_info(user=Depends(get_current_user)):
    if not user:
        return {"error": "user is not authenticated"}
    user_id = user["id"]

    return {"msg": "this is yet to be implemented"}

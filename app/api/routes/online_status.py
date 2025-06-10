from fastapi import APIRouter, status, HTTPException

from app.config.redisconnection import redisConnection
from app.config.settings import EXPIRY_STATUS_TIME, ONLINE


router = APIRouter(prefix="/status", tags=[""])


@router.post(
    "",
    status_code=status.HTTP_200_OK,
)
async def online_status(bot_id: str):
    client = redisConnection.client
    if client:
        client.set(f"bot:{bot_id}", ONLINE, ex=EXPIRY_STATUS_TIME)
        return {"message": "successfully stored"}
    return {"message": "not successfully stored"}


@router.get(
    "/{bot_id}",
    status_code=status.HTTP_200_OK,
)
async def get_online_status(bot_id: str):
    client = redisConnection.client
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis client not available"
        )
    
    status = client.get(f"bot:{bot_id}")
    is_online = status is not None and status.decode('utf-8') == ONLINE
    
    return {
        "bot_id": bot_id,
        "status": "online" if is_online else "offline"
    }


@router.post(
    "/user",
    status_code=status.HTTP_200_OK,
)
async def user_online_status(user_email: str, bot_id: str):
    client = redisConnection.client
    if client:
        client.set(f"user:{user_email}:{bot_id}", ONLINE, ex=EXPIRY_STATUS_TIME)
        return {"message": "successfully stored"}
    return {"message": "not successfully stored"}


@router.get(
    "/user/{user_email}/{bot_id}",
    status_code=status.HTTP_200_OK,
)
async def get_user_online_status(user_email: str, bot_id: str):
    client = redisConnection.client
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis client not available"
        )
    status = client.get(f"user:{user_email}:{bot_id}")
    is_online = status is not None and status.decode('utf-8') == ONLINE
    return {
        "user_email": user_email,
        "bot_id": bot_id,
        "status": "online" if is_online else "offline"
    }
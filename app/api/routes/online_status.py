from fastapi import APIRouter, status

from app.config.redisconnection import redisConnection
from app.config.settings import EXPIRY_STATUS_TIME, ONLINE


router = APIRouter(prefix="/status", tags=[""])


@router.post(
    "",
    status_code=status.HTTP_200_OK,
)
async def online_status(user_id: str):
    client = redisConnection.client
    if client:
        client.set(user_id, ONLINE, ex=EXPIRY_STATUS_TIME)
        return {"message": "successfully stored"}
    return {"message": "not successfully stored"}

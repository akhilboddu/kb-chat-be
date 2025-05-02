from fastapi import APIRouter
from app.api.routes.agent import router as agent_router
from app.api.routes.chat import router as chat_router
from app.api.routes.file import router as file_router
from app.api.routes.scrape import router as scrape_router
from app.api.routes.bot import router as bot_router
from app.api.routes.payment import router as payment_router

router = APIRouter()

# Include all routers with their prefix paths
router.include_router(agent_router)
router.include_router(chat_router)
router.include_router(file_router)
router.include_router(scrape_router)
router.include_router(bot_router) 
router.include_router(payment_router)
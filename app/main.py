import logging
import os
import json
from pathlib import Path
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import uvicorn
from app.config.redisconnection import redisConnection
from app.config.dbconnection import get_db_pool
from app.core.config import llm
from app.api.routes import router
from app.api.routes import health as health_routes
from app.worker.celery_app import celery_app
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.quota_guard import QuotaGuardMiddleware
from app.middleware.widget_cors_filter import WidgetCORSFilter
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure a FastAPI application."""

    app = FastAPI(
        title="Multi-Tenant AI Sales Agent API",
        description="API for managing AI sales agents and WebSocket chat.",
        version="1.0.0",
    )

    # --- CORS Middleware Configuration ---
    # Widget-specific CORS configuration
    # Allow all origins for widget endpoints only
    
    # Check if we're in development mode
    is_development = os.getenv("ENVIRONMENT", "development").lower() == "development"
    
    if is_development:
        # Allow all origins in development for all endpoints
        cors_origins = ["*"]
        allow_credentials = False  # Must be False when using "*"
        print("CORS: Development mode - allowing all origins for all endpoints")
    else:
        # Production: allow all origins for widget endpoints, restrict others
        cors_origins = ["https://deskforce.co.za","http://localhost:8080"]
        allow_credentials = True
        print("CORS: Production mode - allowing all origins for widget endpoints only")
    
    redisConnection.connect()

    # Add rate limiting middleware (relaxed for development)
    app.add_middleware(RateLimitMiddleware, 
                      calls=500, 
                      period=60, 
                      auth_calls=100, 
                      auth_period=60)
    
    # Add quota guard middleware (disabled by default, enable with ENABLE_QUOTA_GUARD=true)
    app.add_middleware(QuotaGuardMiddleware)

    # CORS Middleware for all routes (widget endpoints will be accessible from any origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type", 
            "Authorization",
            "X-Requested-With",
            "Origin",
            "User-Agent",
        ],
        expose_headers=["content-type", "content-length", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"],
    )

    # After CORSMiddleware addition, add WidgetCORSFilter with allowed paths
    widget_allowed_paths = [
        "/api/bots/{bot_id}/config",
        "/api/bots/{bot_id}/conversations",
        "/api/conversations/{conversation_id}",
        "/api/conversations/{conversation_id}/messages",
        "/api/bots/{bot_id}/conversations/by-email/{email}",
        "/api/status/user",
        "/api/status/{bot_id}",
        "/api/ws/{conversation_id}",
    ]
    app.add_middleware(WidgetCORSFilter, allowed_paths=widget_allowed_paths, allowed_origins=cors_origins)

    # Mount all routes from the router with /api prefix
    app.include_router(router, prefix="/api")
    
    # Mount comprehensive health check routes
    app.include_router(health_routes.router, prefix="")

    @app.get("/version")
    async def get_version():
        """Get current deployment version information for both frontend and backend."""
        try:
            # Try multiple possible paths for build numbers file
            possible_paths = [
                Path("/tmp/build-numbers.json"),  # Docker container location
                Path(__file__).parent.parent.parent / "deployment" / "build-numbers.json",  # Local development
            ]
            
            for build_numbers_path in possible_paths:
                if build_numbers_path.exists():
                    with open(build_numbers_path, 'r') as f:
                        build_data = json.load(f)
                    return build_data
            
            # Fallback if file doesn't exist anywhere
            return {
                "frontend": {
                    "build": 0,
                    "last_deployed": None
                },
                "backend": {
                    "build": 0,
                    "last_deployed": None
                }
            }
        except Exception as e:
            logger.error(f"Error reading version info: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "Could not read version information"}
            )

    @app.on_event("startup")
    def init_db_pool():
        get_db_pool()

    @app.on_event("shutdown")
    def close_db_pool():
        get_db_pool().closeall()

    return app


# Create the FastAPI application instance
app = create_app()

# Log startup information
print("FastAPI app initialized.")
if not llm:
    print("WARNING: LLM is not configured. Agent functionality will be limited.")

# For development server
if __name__ == "__main__":
    print("Starting Uvicorn server...")
    # Use reload=True for development to automatically reload on code changes
    # Exclude certain directories from the reloader
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=[
            "./db/*",
            "./venv/*",
            "./.git/*",
            "./.pytest_cache/*",
            "./__pycache__/*",
            "./app/__pycache__/*",
            "./tests/*",
            "./tests/__pycache__/*",
        ],
    )

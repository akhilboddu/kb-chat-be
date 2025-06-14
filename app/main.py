import logging
import os
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
    # Get allowed origins from environment or use defaults
    # Format for CORS_ORIGINS: comma-separated URLs like "https://example.com,https://app.example.com"
    cors_origins_str = os.getenv("CORS_ORIGINS", "")
    additional_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()] if cors_origins_str else []

    # Default development origins
    default_origins = [
        "https://deskforce.co.za",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://chatwise-dev-aryan.netlify.app",
        
    ]

    # Combine default and environment-provided origins, filtering out empty strings and duplicates
    all_origins = default_origins + additional_origins
    origins = list(set(all_origins))  # Remove duplicates
    
    print(f"CORS Origins configured: {origins}")  # Debug logging
    redisConnection.connect()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["content-type", "content-length"],
    )

    # Mount all routes from the router
    app.include_router(router)
    
    # Mount comprehensive health check routes
    app.include_router(health_routes.router, prefix="")

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

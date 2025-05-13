import logging
import os
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import uvicorn
from app.core.db_manager import init_db
from app.core.config import llm
from app.api.routes import router

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
    additional_origins = cors_origins_str.split(",") if cors_origins_str else []

    # Default development origins
    default_origins = [
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://chatwise-dev-aryan.netlify.app",
    ]

    # Combine default and environment-provided origins, filtering out empty strings
    origins = default_origins + [origin for origin in additional_origins if origin]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["content-type", "content-length"],
    )

    # Initialize database
    init_db()

    # Mount all routes from the router
    app.include_router(router)

    # Add health check endpoint for AWS
    @app.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
    async def health_check():
        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"status": "healthy"}
        )

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
    # Exclude the chromadb data directory from the reloader to prevent restarts during KB operations
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=[
            "./chromadb_data/*",
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

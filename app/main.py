import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.db_manager import init_db
from app.core.config import llm
from app.api.routes import router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app() -> FastAPI:
    """Create and configure a FastAPI application."""
    
    app = FastAPI(
        title="Multi-Tenant AI Sales Agent API",
        description="API for managing AI sales agents and WebSocket chat.",
        version="1.0.0"
    )
    
    # --- CORS Middleware Configuration ---
    origins = [
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://chatwise-dev-aryan.netlify.app"
    ] 

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["content-type", "content-length"]
    )

    # Initialize database
    init_db()
    
    # Mount all routes from the router
    app.include_router(router)
    
    return app

# Create the FastAPI application instance
app = create_app()

# Log startup information
print("FastAPI app initialized.")
if not llm:
    print("WARNING: LLM is not configured. Agent functionality will be limited.")

# For development server
if __name__ == "__main__":
    import uvicorn
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
            "./tests/__pycache__/*"
        ]
    ) 
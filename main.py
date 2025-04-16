#!/usr/bin/env python3
# main.py - Entry point for the application

# Import the app from the new structure
from app.main import app

# Run with Uvicorn if this script is executed directly
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
        reload_excludes=["./chromadb_data/*"]
    ) 
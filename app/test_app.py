from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os

# Create simple test app
app = FastAPI(
    title="Chatwise API Test App",
    description="Simple test app for Docker deployment testing",
    version="1.0.0"
)

# CORS Middleware Configuration
origins = ["*"]  # All origins for testing

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", status_code=status.HTTP_200_OK)
async def root():
    return {"message": "Chatwise API is running!"}

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "healthy"}
    )

@app.get("/env", status_code=status.HTTP_200_OK)
async def environment():
    env_vars = {
        "CHROMADB_PATH": os.getenv("CHROMADB_PATH", "Not set"),
        "SQLITE_DB_DIR": os.getenv("SQLITE_DB_DIR", "Not set"),
        "TRANSFORMERS_CACHE": os.getenv("TRANSFORMERS_CACHE", "Not set"),
        "HF_HOME": os.getenv("HF_HOME", "Not set"),
        "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": os.getenv("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "Not set")
    }
    return JSONResponse(content=env_vars)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("test_app:app", host="0.0.0.0", port=8000) 
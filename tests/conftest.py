import os
import pytest
import asyncio
from fastapi.testclient import TestClient
from dotenv import dotenv_values

from app.main import create_app
from app.core.db_manager import init_db

# Load test environment variables
@pytest.fixture(scope="session", autouse=True)
def load_env():
    """Load environment variables from .env.test file before running tests."""
    config = dotenv_values(".env.test")
    for key, value in config.items():
        os.environ[key] = value
    
    # Check if essential test environment variables are loaded
    assert os.environ.get("CHROMADB_PATH") == "./chromadb_data_test"

# Create a fresh test client for each test
@pytest.fixture
def client():
    """Create a FastAPI TestClient for testing endpoints."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

# Fixture to get an event loop for async tests
@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for running async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# Fixture to initialize test database
@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Initialize the test databases before running tests."""
    init_db()
    yield 
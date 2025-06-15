# ChatWise - AI Sales Agent API

ChatWise provides a multi-tenant AI sales agent API that allows businesses to create and manage AI agents tailored to their sales process.

## Project Structure

The application has been refactored into a modular structure:

```
chatwise-be/
├── app/                    # Main application package
│   ├── api/                # API endpoints and routes
│   │   └── routes/         # Route modules by domain
│   ├── models/             # Pydantic models
│   ├── services/           # Background services
│   └── utils/              # Utility functions
├── chromadb_data/          # Vector database storage
├── config.py               # Global configuration
├── db_manager.py           # Database operations
├── file_parser.py          # File parsing utilities
├── kb_manager.py           # Knowledge base management
├── main.py                 # Application entry point
├── requirements.txt        # Dependencies
└── scraper.py              # Web scraper
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/chatwise-be.git
cd chatwise-be
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
Create a `.env` file in the root directory with:
```
OPENAI_API_KEY=your_openai_api_key

# HuggingFace Embeddings Configuration (Recommended)
USE_FLEXIBLE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=huggingface
HUGGINGFACE_MODEL=mixedbread-ai/mxbai-embed-large-v1

# Worker Safety Configuration (CRITICAL for stability)
CELERY_WORKER_POOL=threads
TOKENIZERS_PARALLELISM=false
OMP_NUM_THREADS=1

# Celery Task Time Limits (optional)
UPLOAD_SOFT_LIMIT=1800  # Upload task soft limit in seconds (default: 1800 = 30 min)
UPLOAD_HARD_LIMIT=2400  # Upload task hard limit in seconds (default: 2400 = 40 min)
SCRAPE_SOFT_LIMIT=600   # Scrape task soft limit in seconds (default: 600 = 10 min)
SCRAPE_HARD_LIMIT=900   # Scrape task hard limit in seconds (default: 900 = 15 min)

# Performance Options (optional)
SKIP_CONTEXT_GENERATION=false  # Skip contextual RAG generation for faster uploads (default: false)
```

**📋 See `.env.example` for complete configuration options.**

## Running the Application

Start the development server with hot reload (tests excluded):

```bash
./start.sh
```

Or manually:

```bash
uvicorn app.main:app --reload --reload-exclude="tests/*" --host 0.0.0.0 --port 8000
```

The API will be available at http://localhost:8000.

## Testing

Run all tests with the provided test script:

```bash
./run_tests.sh
```

Run specific tests:

```bash
./run_tests.sh tests/api/routes/test_agent.py -v
```

See the detailed testing documentation in [tests/README.md](tests/README.md).

## API Documentation

Once the server is running, API documentation is available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🚀 HuggingFace Embeddings Migration

**This system has been migrated from Cohere to HuggingFace embeddings for improved stability and performance.**

### Key Benefits
- ✅ **Eliminated segmentation faults** with thread-based Celery workers
- ✅ **No API rate limits** - fully local processing
- ✅ **Improved performance** with 1024-dimensional embeddings
- ✅ **Zero external dependencies** for embeddings

### Quick Start
```bash
# Test embeddings functionality
python scripts/test_embeddings.py --provider=huggingface

# Test worker safety (no segfaults)
python scripts/test_worker_safety.py --iterations=10

# Restart workers with thread pool
./restart_workers.sh
```

📋 **Complete migration guide**: [HUGGINGFACE_MIGRATION_GUIDE.md](HUGGINGFACE_MIGRATION_GUIDE.md)

## Features

- Multi-tenant knowledge bases for different agents
- File upload and parsing (PDF, DOCX, etc.)
- Web scraping integration
- Conversation memory and history
- Human agent handoff capabilities
- Configuration management 
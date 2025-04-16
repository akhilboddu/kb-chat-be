#!/bin/bash

# Start the FastAPI application with hot reload, excluding tests
echo "Starting FastAPI application with hot reload (tests excluded)..."
python3 -m uvicorn app.main:app --reload --reload-exclude="tests/*" --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8000} 
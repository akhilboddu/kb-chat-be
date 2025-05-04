#!/bin/bash
set -e

# Setup script for AWS deployment
echo "Starting Chatwise API for AWS deployment..."

# Check if environment variables are set
if [ -z "$DEEPSEEK_API_KEY" ] && [ -z "$GOOGLE_API_KEY" ]; then
  echo "WARNING: No LLM API keys detected. The application will run with limited functionality."
fi

# Create necessary directories if they don't exist
mkdir -p /app/db
mkdir -p /app/chromadb_data

# Ensure the database directory has correct permissions
chown -R appuser:appuser /app/db
chown -R appuser:appuser /app/chromadb_data

# Start the application with uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} 
# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    TRANSFORMERS_CACHE=/app/.cache/transformers \
    HF_HOME=/app/.cache/huggingface \
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
    HOME=/home/appuser

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        wget \
        curl \
        gcc \
        libpq-dev \
        ca-certificates \
        procps \
        net-tools && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user with a home directory and set the correct permissions
RUN groupadd -r appuser && \
    useradd -r -g appuser -m -d /home/appuser appuser && \
    mkdir -p /home/appuser && \
    chown -R appuser:appuser /home/appuser

# Set the working directory in the container
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---- Pre-fetch critical models ----
# Download the embedding model during build so that the container starts fast
# (otherwise first-start may take >3 minutes and fail health-checks).
RUN python - << 'PY'
from sentence_transformers import SentenceTransformer
# This will download and cache the model under $TRANSFORMERS_CACHE
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
print('✅ HuggingFace model pre-downloaded')
PY

# Copy the rest of the application code with appropriate ownership
COPY --chown=appuser:appuser . .

# Ensure cache directory exists with correct permissions
RUN mkdir -p /app/.cache && \
    chown -R appuser:appuser /app/.cache

# Switch to non-root user
USER appuser

# Expose app port
EXPOSE 8000

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch FastAPI app using Uvicorn with configurable workers
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]

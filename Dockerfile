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
    HOME=/home/appuser \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system dependencies required for Playwright browsers
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        wget \
        curl \
        gcc \
        libpq-dev \
        ca-certificates \
        fonts-liberation \
        libappindicator3-1 \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libgtk-3-0 \
        libnspr4 \
        libnss3 \
        libx11-6 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        xdg-utils \
        libu2f-udev \
        libvulkan1 \
        --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user with a home directory and set the correct permissions
RUN groupadd -r appuser && \
    useradd -r -g appuser -m -d /home/appuser appuser && \
    mkdir -p /home/appuser && \
    chown -R appuser:appuser /home/appuser

# Set the working directory in the container
WORKDIR /app

# Create and prepare necessary directories
RUN mkdir -p /app/chromadb_data /ms-playwright && \
    chmod -R 777 /app/chromadb_data /ms-playwright

# Copy requirements.txt and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY --chown=appuser:appuser . .

# Pre-download sentence transformer model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && \
    chown -R appuser:appuser /app/.cache

# Switch to non-root user
USER appuser

# Install Playwright browser binaries for the correct user
RUN playwright install

# Expose app port
EXPOSE 8000

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch FastAPI app using Uvicorn with multiple workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

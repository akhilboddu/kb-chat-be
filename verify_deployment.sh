#!/bin/bash
# Deployment Verification Script
# Use after deployment to verify the application is running properly

set -e

# Get the base URL from the first argument or use localhost
BASE_URL=${1:-"http://localhost:8000"}
echo "Testing deployment at $BASE_URL"

# Test health endpoint
echo "Testing health endpoint..."
HEALTH_RESPONSE=$(curl -s "$BASE_URL/health")
if [[ "$HEALTH_RESPONSE" == *"healthy"* ]]; then
  echo "✅ Health check passed"
else
  echo "❌ Health check failed"
  exit 1
fi

# Print success message
echo "✅ Deployment verification completed successfully"
echo "Your API is running at: $BASE_URL"
# AWS Deployment Guide for Chatwise API

This guide provides instructions for deploying the Chatwise API on AWS using Docker.

## Prerequisites

- AWS Account
- AWS CLI installed and configured
- Docker and Docker Compose installed locally
- Familiarity with AWS services (ECR, ECS, or Elastic Beanstalk)

## Testing Before Deployment

Before deploying to AWS, you can test locally with Docker Compose:

```bash
# Create a .env.docker file with necessary environment variables
# See .env.example for required variables

# Build and start the application
docker compose build
docker compose up -d

# Check application logs
docker compose logs -f

# Test the health endpoint
curl http://localhost:8000/health

# Verify the deployment
./verify_deployment.sh
```

If you experience any issues, you can use the test application for simpler diagnostics:

```bash
# Build and run the test application
docker build -t chatwise-test -f Dockerfile.test .
docker run -d -p 8000:8000 chatwise-test
curl http://localhost:8000/
```

## AWS Deployment Cheat Sheet

Here's a quick reference for common AWS deployment commands:

### Amazon ECR

```bash
# Login to ECR
aws ecr get-login-password --region <your-region> | docker login --username AWS --password-stdin <your-aws-account-id>.dkr.ecr.<your-region>.amazonaws.com

# Create a repository (if not exists)
aws ecr create-repository --repository-name chatwise-api

# Build, tag and push the Docker image
docker build -t chatwise-api .
docker tag chatwise-api:latest <your-aws-account-id>.dkr.ecr.<your-region>.amazonaws.com/chatwise-api:latest
docker push <your-aws-account-id>.dkr.ecr.<your-region>.amazonaws.com/chatwise-api:latest
```

### ECS Deployment

```bash
# Create ECS task definition (first time)
aws ecs register-task-definition --cli-input-json file://task-definition.json

# Update ECS service
aws ecs update-service --cluster <your-cluster> --service <your-service> --force-new-deployment
```

### Verify Deployment

After deployment, verify that the application is running:

```bash
# Replace with your actual AWS endpoint
./verify_deployment.sh https://your-api-endpoint.amazonaws.com
```

## Deployment Options

### Option 1: Amazon ECS with Fargate (Serverless)

1. **Create an Amazon ECR Repository**

```bash
aws ecr create-repository --repository-name chatwise-api
```

2. **Authenticate Docker to your ECR Registry**

```bash
aws ecr get-login-password --region <your-region> | docker login --username AWS --password-stdin <your-aws-account-id>.dkr.ecr.<your-region>.amazonaws.com
```

3. **Build and Tag your Docker Image**

```bash
docker build -t chatwise-api .
docker tag chatwise-api:latest <your-aws-account-id>.dkr.ecr.<your-region>.amazonaws.com/chatwise-api:latest
```

4. **Push the Image to ECR**

```bash
docker push <your-aws-account-id>.dkr.ecr.<your-region>.amazonaws.com/chatwise-api:latest
```

5. **Create an ECS Cluster, Task Definition, and Service**
   - Use the AWS Management Console to create these resources
   - Specify your ECR image in the task definition
   - Configure environment variables for your API keys
   - Set up persistent storage using EFS if needed for ChromaDB data
   - Configure health checks to use the `/health` endpoint

### Option 2: AWS Elastic Beanstalk with Docker

1. **Install the EB CLI**

```bash
pip install awsebcli
```

2. **Initialize EB Application**

```bash
eb init -p docker chatwise-api
```

3. **Create an EB Environment**

```bash
eb create chatwise-api-prod
```

4. **Deploy the Application**

```bash
eb deploy
```

## Environment Variables

Configure these environment variables in your AWS service:

- `CHROMADB_PATH`: Path to ChromaDB data directory
- `SQLITE_DB_DIR`: Directory for SQLite database
- `SQLITE_DB_FILENAME`: SQLite database filename
- `TRANSFORMERS_CACHE`: Path to store transformer models (defaults to /app/.cache/transformers)
- `HF_HOME`: Path for HuggingFace cache (defaults to /app/.cache/huggingface)
- `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION`: Set to "python" to avoid protobuf issues
- `DEEPSEEK_API_KEY`: Your DeepSeek API key
- `DEEPSEEK_API_BASE`: DeepSeek API base URL
- `GOOGLE_API_KEY`: Your Google API key
- `CORS_ORIGINS`: Comma-separated list of allowed origins for CORS

## Persistent Storage

For data persistence:
- Use Amazon EFS for ECS deployments
- Use Elastic Beanstalk with EBS volumes for EB deployments

## Monitoring and Logs

- Set up CloudWatch for monitoring and logging
- Configure alarms for your service health

## Security Considerations

- Use AWS Secrets Manager for API keys
- Configure proper IAM permissions
- Use AWS WAF for additional security

## Cost Optimization

- Use Fargate Spot for cost savings in non-critical environments
- Set up CloudWatch alarms for cost monitoring
- Consider Reserved Instances for long-term deployments 
#!/bin/bash

# Deployment script for DigitalOcean Droplet
# Usage: ./deploy.sh [production|staging]

ENVIRONMENT=${1:-production}
GIT_REPO_URL="https://github.com/yourusername/your-repo.git"
APP_NAME="aluquote-backend"
DOCKER_IMAGE="aluquote-backend"

set -e  # Exit on error

echo "🚀 Starting deployment for $ENVIRONMENT environment..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "⚠️  Docker Compose not found. Installing..."
    apt-get update
    apt-get install -y docker-compose
fi

# Backup existing data (if container exists)
if [ "$(docker ps -aq -f name=$APP_NAME)" ]; then
    echo "📦 Backing up existing data..."
    docker exec $APP_NAME tar -czf /tmp/backup-$(date +%Y%m%d-%H%M%S).tar.gz /app/uploads /app/exports 2>/dev/null || true
fi

# Pull latest code
if [ -d ".git" ]; then
    echo "📥 Pulling latest code..."
    git pull origin main || git pull origin master
else
    echo "📥 Cloning repository..."
    git clone $GIT_REPO_URL .
fi

# Build Docker image
echo "🔨 Building Docker image..."
docker build -t $DOCKER_IMAGE:latest .

# Stop and remove existing container
if [ "$(docker ps -aq -f name=$APP_NAME)" ]; then
    echo "🛑 Stopping existing container..."
    docker stop $APP_NAME || true
    docker rm $APP_NAME || true
fi

# Start new container
if [ -f "docker-compose.yml" ]; then
    echo "🚀 Starting services with Docker Compose..."
    docker-compose up -d
else
    echo "🚀 Starting container..."
    docker run -d \
        --name $APP_NAME \
        -p 8000:8000 \
        --restart unless-stopped \
        -v $(pwd)/uploads:/app/uploads \
        -v $(pwd)/exports:/app/exports \
        $DOCKER_IMAGE:latest
fi

# Wait for health check
echo "⏳ Waiting for application to start..."
sleep 10

# Health check
if curl -f http://localhost:8000/api/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Deployment successful!${NC}"
    echo "🌐 Application is running at http://localhost:8000"
    echo "📊 Health check: http://localhost:8000/api/health"
else
    echo -e "${YELLOW}⚠️  Health check failed. Check logs with: docker logs $APP_NAME${NC}"
    docker logs $APP_NAME --tail 50
    exit 1
fi

# Clean up old images
echo "🧹 Cleaning up old Docker images..."
docker image prune -f

echo -e "${GREEN}✨ Deployment complete!${NC}"

#!/bin/bash

# Markt Docker Deployment Script

set -e

echo "🚀 Starting Markt Docker deployment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create necessary directories
print_status "Creating necessary directories..."
mkdir -p logs uploads docker/nginx/conf.d

# Copy environment file if it doesn't exist
if [ ! -f .env ]; then
    print_status "Creating .env file from template..."
    cp docker/env.example .env
    print_warning "Please edit .env file with your production values!"
fi

# Build and start services
print_status "Building and starting services..."
docker-compose -f docker-compose.production.yml up -d --build

# Wait for services to be healthy
print_status "Waiting for services to be healthy..."
sleep 30

# Check service health
print_status "Checking service health..."

# Check PostgreSQL
if docker-compose -f docker-compose.production.yml exec -T postgres pg_isready -U markt -d markt_db > /dev/null 2>&1; then
    print_status "✅ PostgreSQL is healthy"
else
    print_error "❌ PostgreSQL is not healthy"
fi

# Check Redis
if docker-compose -f docker-compose.production.yml exec -T redis redis-cli ping > /dev/null 2>&1; then
    print_status "✅ Redis is healthy"
else
    print_error "❌ Redis is not healthy"
fi

# Check Application
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    print_status "✅ Application is healthy"
else
    print_error "❌ Application is not healthy"
fi

# Run database migrations
print_status "Running database migrations..."
docker-compose -f docker-compose.production.yml exec -T markt-app flask db upgrade

print_status "✅ Deployment completed successfully!"

echo ""
echo "📊 Service Status:"
docker-compose -f docker-compose.production.yml ps

echo ""
echo "🌐 Access your application:"
echo "   - API: http://localhost/api/v1"
echo "   - Health: http://localhost/health"
echo "   - Redis Insight: http://localhost:8001 (if monitoring profile is enabled)"

echo ""
echo "📝 Useful commands:"
echo "   - View logs: docker-compose -f docker-compose.production.yml logs -f"
echo "   - Stop services: docker-compose -f docker-compose.production.yml down"
echo "   - Restart services: docker-compose -f docker-compose.production.yml restart"
echo "   - Update and redeploy: ./docker/deploy.sh" 
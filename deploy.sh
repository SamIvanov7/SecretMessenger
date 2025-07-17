#!/bin/bash

echo "Deploying Messenger application..."

# Pull latest changes
git pull origin main

# Build images
docker-compose -f docker-compose.yml -f docker-compose.prod.yml build

# Run migrations
docker-compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head

# Start services
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Clean up old images
docker image prune -f

echo "Deployment complete!"
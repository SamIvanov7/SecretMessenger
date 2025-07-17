#!/bin/bash

echo "Setting up Messenger development environment..."

# Create necessary directories
mkdir -p backend/uploads
mkdir -p backend/alembic/versions
mkdir -p frontend/css/components

# Copy environment file
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env file. Please update it with your configuration."
fi

# Generate secret key
SECRET_KEY=$(openssl rand -hex 32)
sed -i "s/your-secret-key-change-this-in-production/$SECRET_KEY/g" .env

# Create placeholder icon files
touch frontend/icon-192.png
touch frontend/icon-512.png
touch frontend/badge-72.png

echo "Setup complete! Run 'docker-compose up' to start the application."
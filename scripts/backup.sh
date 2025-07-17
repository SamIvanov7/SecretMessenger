#!/bin/bash

BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="messenger"

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup PostgreSQL
echo "Backing up PostgreSQL..."
docker-compose exec -T postgres pg_dump -U messenger $DB_NAME | gzip > $BACKUP_DIR/postgres_$TIMESTAMP.sql.gz

# Backup uploads
echo "Backing up uploads..."
tar -czf $BACKUP_DIR/uploads_$TIMESTAMP.tar.gz -C backend uploads/

# Clean old backups (keep last 7 days)
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete

echo "Backup completed: $TIMESTAMP"
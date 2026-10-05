#!/bin/bash
# Дамп Postgres в ./backups, хранится BACKUP_KEEP_DAYS дней (по умолчанию 14)
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
mkdir -p backups
chmod 700 backups
file="backups/voice_assistant_$(date +%Y%m%d_%H%M%S).sql.gz"

docker compose exec -T postgres pg_dump -U voice -d voice_assistant --no-owner | gzip > "$file"
chmod 600 "$file"
find backups -name 'voice_assistant_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "Backup: $file ($(du -h "$file" | cut -f1))"

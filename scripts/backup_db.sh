#!/usr/bin/env bash
# Daglig Postgres-backup for Lampeland Bakeri.
#
# Bruk via cron, f.eks. (i sudo crontab -e -u poshubadmin):
#   15 2 * * * /home/poshubadmin/bakeri/scripts/backup_db.sh >> /var/log/bakeri-backup.log 2>&1
#
# Beholder 14 daglige + 8 ukentlige (søndag) backups.
# Send filer til ekstern lagring (f.eks. rclone til S3/Backblaze) via en separat cron.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/home/poshubadmin/backups}"
DB_NAME="${DB_NAME:-lampeland_bakeri}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-postgres}"
PGPASSWORD="${PGPASSWORD:-postgres}"
export PGPASSWORD

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"

TS="$(date +%Y%m%d_%H%M%S)"
DAILY_FILE="$BACKUP_DIR/daily/bakeri_${TS}.sql.gz"

echo "[$(date -Is)] Starter backup -> $DAILY_FILE"
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
  --no-owner --clean --if-exists "$DB_NAME" \
  | gzip -9 > "$DAILY_FILE"

# Verifiser at dumpen ikke er tom
SIZE=$(stat -c%s "$DAILY_FILE")
if [ "$SIZE" -lt 1024 ]; then
  echo "[$(date -Is)] FEIL: backup er for liten ($SIZE bytes)" >&2
  exit 1
fi
echo "[$(date -Is)] Backup OK ($SIZE bytes)"

# Søndag: kopier til weekly
if [ "$(date +%u)" = "7" ]; then
  cp "$DAILY_FILE" "$BACKUP_DIR/weekly/bakeri_week_$(date +%Y%V).sql.gz"
  echo "[$(date -Is)] Ukesbackup lagret"
fi

# Behold 14 daglige + 8 ukentlige
find "$BACKUP_DIR/daily"  -name 'bakeri_*.sql.gz' -mtime +14 -delete
find "$BACKUP_DIR/weekly" -name 'bakeri_week_*.sql.gz' -mtime +60 -delete

echo "[$(date -Is)] Ferdig"

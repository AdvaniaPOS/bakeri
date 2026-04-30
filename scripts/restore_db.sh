#!/usr/bin/env bash
# Restore en backup-fil (gzippet pg_dump) til lampeland_bakeri.
#
# ADVARSEL: Dette dropper og gjenoppretter databasen. Bruk ALDRI mot prod
# uten først å ha tatt en frisk dump.
#
# Bruk:
#   ./scripts/restore_db.sh ~/backups/daily/bakeri_20260430_021500.sql.gz
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Bruk: $0 <path/til/backup.sql.gz>"
  exit 1
fi

FILE="$1"
DB_NAME="${DB_NAME:-lampeland_bakeri}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-postgres}"
PGPASSWORD="${PGPASSWORD:-postgres}"
export PGPASSWORD

# Auto-detekter psql
PSQL="${PSQL:-}"
if [ -z "$PSQL" ]; then
  if command -v psql >/dev/null 2>&1; then
    PSQL="$(command -v psql)"
  else
    PSQL="$(ls -1 /usr/lib/postgresql/*/bin/psql 2>/dev/null | sort -V | tail -n1 || true)"
  fi
fi
if [ -z "$PSQL" ] || [ ! -x "$PSQL" ]; then
  echo "FEIL: fant ikke psql. Installer postgresql-client eller sett PSQL-variabelen." >&2
  exit 1
fi

if [ ! -f "$FILE" ]; then
  echo "FEIL: fant ikke $FILE" >&2
  exit 1
fi

read -p "Dette vil OVERSKRIVE databasen '$DB_NAME'. Er du sikker? (skriv JA): " CONF
if [ "$CONF" != "JA" ]; then
  echo "Avbrutt."
  exit 1
fi

echo "Restorer fra $FILE (med $PSQL)..."
gunzip -c "$FILE" | "$PSQL" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1
echo "Restore ferdig. Husk: sudo systemctl restart bakeri-backend"

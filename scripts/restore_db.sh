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

APP_ENV_VALUE="${APP_ENV:-}"
if [ -z "$APP_ENV_VALUE" ]; then
  REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
  ENV_FILE="$REPO_DIR/.env"
  if [ -f "$ENV_FILE" ]; then
    APP_ENV_VALUE="$(grep -E '^APP_ENV=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r' | sed -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//')"
  fi
fi

case "${APP_ENV_VALUE,,}" in
  production|prod|staging)
    if [ "${ALLOW_PROD_RESTORE:-}" != "YES_I_UNDERSTAND" ]; then
      echo "Refuserer aa restore over production-liknende database uten eksplisitt override." >&2
      echo "Sett ALLOW_PROD_RESTORE=YES_I_UNDERSTAND hvis dette er bevisst." >&2
      exit 2
    fi
    ;;
esac

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

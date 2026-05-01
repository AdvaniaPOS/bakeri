#!/bin/bash
# Backup-skript for Lampeland Bakeri.
# Tar daglig dump av databasen, krymper, krypterer og roterer.
#
# Bruk:
#   ./scripts/backup.sh                  # kjører backup
#   crontab -e:  0 3 * * * /home/poshubadmin/bakeri/scripts/backup.sh >> /var/log/bakeri-backup.log 2>&1
#
# Miljøvariabler (sett i /etc/default/bakeri-backup eller .env):
#   BACKUP_DIR=/var/backups/bakeri        # hvor backupene lagres
#   DATABASE_URL=postgresql://...         # leses fra .env hvis ikke satt
#   RETENTION_DAYS=14                     # antall dager å beholde
#   BACKUP_GPG_RECIPIENT=admin@dom.no     # valgfritt: krypterer dumpen
#   BACKUP_S3_BUCKET=s3://my-bucket/dir   # valgfritt: kopierer til S3 (krever aws-cli)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Last .env hvis variabler ikke er satt.
if [ -f .env ]; then
    set -a; source .env; set +a
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/bakeri}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP="$(date +%F_%H%M%S)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

if [ -z "${DATABASE_URL:-}" ]; then
    echo "FEIL: DATABASE_URL er ikke satt" >&2
    exit 1
fi

OUT="$BACKUP_DIR/bakeri-$TIMESTAMP"

case "$DATABASE_URL" in
    sqlite:///*)
        DB_PATH="${DATABASE_URL#sqlite:///}"
        # Bruker .backup-API-et så vi får konsistent snapshot selv om appen skriver.
        sqlite3 "$DB_PATH" ".backup '$OUT.db'"
        gzip -9 "$OUT.db"
        OUT_FILE="$OUT.db.gz"
        ;;
    postgresql*|postgres*)
        # pg_dump i custom-format (komprimert + parallell-restore mulig).
        pg_dump --format=custom --no-owner --no-acl --dbname="$DATABASE_URL" --file="$OUT.dump"
        OUT_FILE="$OUT.dump"
        ;;
    *)
        echo "FEIL: ukjent DATABASE_URL: $DATABASE_URL" >&2
        exit 2
        ;;
esac

echo "Backup OK: $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"

# Kryptering (valgfritt).
if [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
    gpg --batch --yes --trust-model always --encrypt -r "$BACKUP_GPG_RECIPIENT" "$OUT_FILE"
    rm -f "$OUT_FILE"
    OUT_FILE="${OUT_FILE}.gpg"
    echo "Kryptert: $OUT_FILE"
fi

# Off-site (S3-kompatibel) — valgfritt.
if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
    aws s3 cp "$OUT_FILE" "${BACKUP_S3_BUCKET%/}/$(basename "$OUT_FILE")" --only-show-errors
    echo "Lastet opp til $BACKUP_S3_BUCKET"
fi

# Rotasjon: slett dumper eldre enn RETENTION_DAYS.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'bakeri-*' -mtime "+$RETENTION_DAYS" -delete
echo "Eldre enn $RETENTION_DAYS dager slettet."

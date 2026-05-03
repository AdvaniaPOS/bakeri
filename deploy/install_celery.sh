#!/usr/bin/env bash
# Install Redis + Celery worker/beat systemd-tjenester for bakeri.
# Kjøres EN gang på serveren med sudo. Idempotent.
set -euo pipefail

REPO_DIR="/home/poshubadmin/bakeri"
SERVICE_DIR="/etc/systemd/system"

echo "==> Sjekker at redis er tilgjengelig pa 127.0.0.1:6379 (forventet i docker)"
if ! redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
  echo "FEIL: redis svarer ikke pa 127.0.0.1:6379. Sjekk at docker-containeren kjorer." >&2
  exit 1
fi
echo "redis OK"

# Disable apt-redis hvis den finnes og er failed (port-konflikt med docker)
if systemctl list-unit-files | grep -q '^redis-server.service'; then
  systemctl disable --now redis-server.service 2>/dev/null || true
  systemctl reset-failed redis-server.service 2>/dev/null || true
fi

echo "==> Sikrer at celery+redis-klient er installert i venv"
sudo -u poshubadmin "$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

echo "==> Kopierer systemd-unit-filer"
cp "$REPO_DIR/deploy/bakeri-worker.service" "$SERVICE_DIR/bakeri-worker.service"
cp "$REPO_DIR/deploy/bakeri-beat.service"   "$SERVICE_DIR/bakeri-beat.service"

echo "==> Reloader systemd"
systemctl daemon-reload
systemctl enable --now bakeri-worker.service
systemctl enable --now bakeri-beat.service

sleep 2
echo "==> Status:"
systemctl is-active bakeri-worker bakeri-beat
echo "==> Ferdig. Sjekk logger med:"
echo "   journalctl -u bakeri-worker -f"
echo "   journalctl -u bakeri-beat -f"

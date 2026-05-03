#!/usr/bin/env bash
# Install Redis + Celery worker/beat systemd-tjenester for bakeri.
# Kjøres EN gang på serveren med sudo. Idempotent.
set -euo pipefail

REPO_DIR="/home/poshubadmin/bakeri"
SERVICE_DIR="/etc/systemd/system"

echo "==> Installerer redis-server"
apt-get update -qq
apt-get install -y -qq redis-server

echo "==> Starter redis"
systemctl enable --now redis-server
systemctl is-active redis-server

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
systemctl is-active redis-server bakeri-worker bakeri-beat
echo "==> Ferdig. Sjekk logger med:"
echo "   journalctl -u bakeri-worker -f"
echo "   journalctl -u bakeri-beat -f"

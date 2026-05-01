#!/usr/bin/env bash
# =============================================================================
# Deploy-skript for Lampeland Bakeri ordresystem
# =============================================================================
# Brukes på serveren. Idempotent og rullbar:
#   1. Husk forrige commit (for rollback)
#   2. git pull
#   3. pip install -r requirements.txt
#   4. (auto_migrate kjører i lifespan ved oppstart)
#   5. npm ci && npm run build (frontend)
#   6. systemctl restart bakeri-backend
#   7. Smoketest mot lokalt /health og /api/v1/products
#   8. Hvis smoketest feiler -> rull tilbake til forrige commit + restart
#
# Kjør:
#   cd ~/bakeri && bash scripts/deploy.sh
# =============================================================================

set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/bakeri}"
SERVICE_NAME="${SERVICE_NAME:-bakeri-backend}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
SMOKE_URL="${SMOKE_URL:-http://127.0.0.1:8000/api/v1/products?page_size=1}"
PYTHON_VENV="${PYTHON_VENV:-$REPO_DIR/.venv/bin/python}"
PIP="${PIP:-$REPO_DIR/.venv/bin/pip}"

cd "$REPO_DIR"

echo "==> Working dir: $(pwd)"
PREV_COMMIT=$(git rev-parse HEAD)
echo "==> Forrige commit (for rollback): $PREV_COMMIT"

echo "==> git pull"
git pull --ff-only

echo "==> pip install -r requirements.txt"
"$PIP" install -r requirements.txt --quiet

if [[ -d "frontend" ]]; then
    echo "==> Bygger frontend"
    pushd frontend >/dev/null
    if [[ -f "package-lock.json" ]]; then
        npm ci --no-audit --no-fund --silent
    else
        npm install --no-audit --no-fund --silent
    fi
    npm run build
    popd >/dev/null
fi

echo "==> Restart $SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "==> Venter på at backend kommer opp..."
ATTEMPT=0
MAX_ATTEMPTS=20
until curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [[ $ATTEMPT -ge $MAX_ATTEMPTS ]]; then
        echo "!! /health svarte ikke etter $MAX_ATTEMPTS forsøk — ruller tilbake."
        git reset --hard "$PREV_COMMIT"
        sudo systemctl restart "$SERVICE_NAME"
        exit 1
    fi
    sleep 1
done
echo "==> /health OK"

# Smoketest av et faktisk API-endepunkt (krever ikke auth hvis åpent; ellers
# bruk SMOKE_URL=/health). Vi godtar 200, 401 og 403 (auth-feil betyr at appen
# faktisk svarer; 5xx er ikke akseptabelt).
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$SMOKE_URL" || echo "000")
if [[ "$HTTP_CODE" =~ ^(200|401|403)$ ]]; then
    echo "==> Smoketest OK ($HTTP_CODE for $SMOKE_URL)"
else
    echo "!! Smoketest feilet: HTTP $HTTP_CODE for $SMOKE_URL — ruller tilbake."
    git reset --hard "$PREV_COMMIT"
    sudo systemctl restart "$SERVICE_NAME"
    exit 1
fi

NEW_COMMIT=$(git rev-parse HEAD)
echo "==> Deploy ferdig: $PREV_COMMIT  ->  $NEW_COMMIT"

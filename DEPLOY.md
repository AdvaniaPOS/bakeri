# Deploy – Lampeland Bakeri Ordresystem

Dette er stegene for å installere og oppdatere systemet på Linux-serveren
(Ubuntu 24.04, samme oppsett som Link-prosjektet).

## Portoversikt (reservert for dette prosjektet)

| Port | Tjeneste | Eksponert |
|------|----------|-----------|
| 8001 | FastAPI backend (gunicorn/uvicorn) | Kun `127.0.0.1` |
| 80   | nginx (samme som Link – ny `server`-blokk) | Offentlig via Cloudflare Tunnel |

> Backend bruker **8001** for å ikke krasje med Link (`8000`) og andre gunicorn-apper.

## 1. Førstegangs installasjon

```bash
# Forutsetninger (kjører trolig allerede)
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip nodejs npm postgresql-client redis-tools nginx git

# Klon repo
cd ~
git clone https://github.com/AdvaniaPOS/bakeri.git
cd bakeri

# Python venv + avhengigheter
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Konfigurasjon
cp .env.example .env
nano .env   # fyll inn JWT_SECRET_KEY, APP_ENCRYPTION_KEY, DATABASE_URL osv.

# Generer secrets
python -c "import secrets; print(secrets.token_urlsafe(64))"   # JWT_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(64))"   # APP_ENCRYPTION_KEY

# Database (Postgres antas å kjøre i Docker på 5432)
# Opprett database hvis den ikke finnes:
PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE lampeland_bakeri;"

# Init schema
python init_db.py
python migrate_schema.py
python migrate_lead_days.py
python migrate_unique_constraints.py

# Frontend build
cd frontend
npm install
npm run build
cd ..
```

## 2. systemd – backend

Lag fil `/etc/systemd/system/bakeri-backend.service`:

```ini
[Unit]
Description=Lampeland Bakeri backend (FastAPI)
After=network.target

[Service]
Type=simple
User=poshubadmin
WorkingDirectory=/home/poshubadmin/bakeri
Environment=PORT=8001
EnvironmentFile=/home/poshubadmin/bakeri/.env
ExecStart=/home/poshubadmin/bakeri/.venv/bin/gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8001 \
  --access-logfile - \
  --error-logfile -
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Aktiver:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bakeri-backend
sudo systemctl status bakeri-backend
```

## 3. nginx – frontend + reverse proxy

Lag fil `/etc/nginx/sites-available/bakeri`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name bakeri.poshub.no;

    root /home/poshubadmin/bakeri/frontend/dist;
    index index.html;

    # SPA-routing
    location / {
        try_files $uri /index.html;
    }

    # API → backend
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    # /docs (FastAPI Swagger) – valgfritt, kan begrenses
    location /docs {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
    }
    location /openapi.json {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
    }

    client_max_body_size 25m;
}
```

Aktiver:
```bash
sudo ln -s /etc/nginx/sites-available/bakeri /etc/nginx/sites-enabled/bakeri
sudo nginx -t
sudo systemctl reload nginx
```

## 4. Cloudflare Tunnel

Legg til ny Published application-rute i Cloudflare Zero Trust:

| Destination | Type | Service |
|-------------|------|---------|
| `bakeri.poshub.no` | Published application | `http://localhost:80` |

Dette matcher samme mønster som `tagly.poshub.no`. Nginx ruter videre basert på `server_name`.

## 5. Oppdatering (etter `git push` fra Windows)

```bash
cd ~/bakeri
git pull

# Backend – nye Python-pakker?
source .venv/bin/activate
pip install -r requirements.txt

# Migrasjoner (kjør de nye)
python migrate_schema.py            # idempotent

# Frontend
cd frontend
npm install
npm run build
cd ..

# Restart
sudo systemctl restart bakeri-backend
sudo systemctl reload nginx
```

## 5b. PDF-rapporter (WeasyPrint)

Backend bruker WeasyPrint for å generere PDF-er (produksjonsrapport,
pakkeliste, ordrebekreftelse, leveringsbekreftelse, etiketter).
WeasyPrint krever noen system-libs:

```bash
sudo apt install -y \
  libpango-1.0-0 libpangoft2-1.0-0 \
  libcairo2 libgdk-pixbuf-2.0-0 \
  libffi-dev shared-mime-info fonts-dejavu-core
```

Etter dette må backend startes på nytt: `sudo systemctl restart bakeri-backend`.

Test at det fungerer:

```bash
curl -I -H "Authorization: Bearer <token>" \
  http://127.0.0.1:8001/api/v1/reports/production/$(date +%F).pdf
# Forventet: Content-Type: application/pdf
```

## 5c. Daglig auto-generering av ordre (cron)

Backend genererer planlagte ordre automatisk når noen logger inn (idempotent
pr dag). For å sikre at det også skjer når ingen logger inn tidlig om
morgenen, legg til en cron-jobb:

```bash
sudo crontab -e -u poshubadmin
```

Legg til:

```cron
# Lampeland Bakeri – generer ordre kl 02:05 hver natt
5 2 * * * cd /home/poshubadmin/bakeri && /home/poshubadmin/bakeri/.venv/bin/python -m scripts.generate_orders --force >> /var/log/bakeri-generate.log 2>&1
```

Sørg for at loggfilen kan skrives:

```bash
sudo touch /var/log/bakeri-generate.log
sudo chown poshubadmin:poshubadmin /var/log/bakeri-generate.log
```

Manuell kjøring (test):

```bash
cd ~/bakeri
.venv/bin/python -m scripts.generate_orders --force
```

Eller via API (krever MANAGER+ token):

```bash
curl -X POST -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:8001/api/v1/admin/horizon/trigger?force=true"
```

## 6. Logger og feilsøking

```bash
# Backend
sudo journalctl -u bakeri-backend -f
sudo journalctl -u bakeri-backend --since "10 min ago"

# Nginx
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log

# Verifiser porter
sudo ss -tulpn | grep -E ':(80|8001)\b'

# Helsesjekk
curl -I http://127.0.0.1:8001/docs
curl -I http://127.0.0.1/
```

## 7. Backup

Vi har et ferdig backup-script som lager komprimerte daglige dumper og roterer dem (14 daglige + ukentlige i 60 dager).

### 7a. Førstegangs-oppsett

```bash
chmod +x ~/bakeri/scripts/backup_db.sh ~/bakeri/scripts/restore_db.sh
mkdir -p ~/backups/daily ~/backups/weekly
sudo touch /var/log/bakeri-backup.log
sudo chown poshubadmin:poshubadmin /var/log/bakeri-backup.log
```

### 7b. Cron (kjøres som poshubadmin)

```bash
sudo crontab -e -u poshubadmin
```

Legg til linja:

```cron
15 2 * * * /home/poshubadmin/bakeri/scripts/backup_db.sh >> /var/log/bakeri-backup.log 2>&1
```

### 7c. Test backupen umiddelbart

```bash
~/bakeri/scripts/backup_db.sh
ls -lh ~/backups/daily/
tail /var/log/bakeri-backup.log
```

### 7d. Restore (når katastrofen rammer)

```bash
~/bakeri/scripts/restore_db.sh ~/backups/daily/bakeri_20260430_021500.sql.gz
sudo systemctl restart bakeri-backend
```

### 7e. Off-site (anbefalt)

Backups på samme server hjelper IKKE ved disk-feil eller ransomware. Vurder rclone/restic mot ekstern lagring (S3, Backblaze B2, OneDrive). Eksempel:

```bash
# Etter backup_db.sh — kopier til ekstern lagring
rclone copy ~/backups/daily b2:bakeri-backups/daily --max-age 24h
```


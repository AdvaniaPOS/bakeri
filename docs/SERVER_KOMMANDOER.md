# Serverkommandoer

Produksjons-cheat sheet for Lampeland Bakeri.

Forutsetninger:
- repo: `/home/poshubadmin/bakeri`
- backend: `bakeri-backend`
- worker: `bakeri-worker`
- beat: `bakeri-beat`
- health: `http://127.0.0.1:8001/health`

## Daglig deploy

```bash
cd /home/poshubadmin/bakeri
git pull --ff-only origin main
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.migrate
cd frontend && npm install && npm run build && cd ..
sudo systemctl restart bakeri-backend bakeri-worker bakeri-beat
sudo nginx -t && sudo systemctl reload nginx
curl http://127.0.0.1:8001/health
```

## Git

```bash
cd /home/poshubadmin/bakeri
git status
git fetch origin
git pull --ff-only origin main
git log --oneline -n 5
git rev-parse HEAD
```

## Restart tjenester

```bash
sudo systemctl restart bakeri-backend
sudo systemctl restart bakeri-worker
sudo systemctl restart bakeri-beat
sudo systemctl reload nginx
sudo systemctl restart docker
sudo reboot
```

## Status

```bash
systemctl is-active bakeri-backend bakeri-worker bakeri-beat nginx docker
sudo systemctl status bakeri-backend
sudo systemctl status bakeri-worker
sudo systemctl status bakeri-beat
sudo systemctl status nginx
docker ps
curl http://127.0.0.1:8001/health
redis-cli -h 127.0.0.1 -p 6379 ping
ss -tulpn | grep 8001
df -h
free -h
uptime
```

## Logger

```bash
sudo journalctl -u bakeri-backend -f
sudo journalctl -u bakeri-worker -f
sudo journalctl -u bakeri-beat -f
sudo journalctl -u bakeri-backend -n 100 --no-pager
sudo journalctl -u bakeri-backend --since "30 min ago"
sudo journalctl -u bakeri-backend --since "1 hour ago" | grep -i error
```

## Docker

```bash
sudo systemctl status docker
docker ps
docker restart <container_navn>
```

## Rollback

```bash
cd /home/poshubadmin/bakeri
git log --oneline -n 10
git checkout <commit_sha>
sudo systemctl restart bakeri-backend bakeri-worker bakeri-beat
```

Tilbake til hovedbranch:

```bash
git checkout main
git pull --ff-only origin main
```

## Tips

- Bruk alltid `git pull --ff-only` pa serveren.
- Kjor `sudo nginx -t` for reload av nginx.
- Etter deploy: sjekk alltid `curl http://127.0.0.1:8001/health`.
- Hvis Celery feiler: sjekk Redis forst med `redis-cli -h 127.0.0.1 -p 6379 ping`.
- Hvis Docker restartes: restart ogsa `bakeri-worker` og `bakeri-beat`.
- Hvis backend ikke starter: `sudo journalctl -u bakeri-backend -n 200 --no-pager`.
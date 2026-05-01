# Pilot- og UAT-sjekkliste — Lampeland Bakeri ordresystem

Bruk denne listen før du gir tilgang til pilotbruker. Avhuk hvert punkt og noter eventuelle avvik. Mål: ingen kritiske feil, og bakerne kan ta i mot dagens drift uten manuelle workarounds.

## 1. Pre-flight (teknisk)

- [ ] Backend-versjon (commit) er notert: `__________`
- [ ] Frontend-build (commit / dato) er notert: `__________`
- [ ] `scripts/deploy.sh` har kjørt uten rollback
- [ ] `/health` svarer 200 fra `https://bakeri.poshub.no/health`
- [ ] `auto_migrate` har lagt til alle nødvendige kolonner (sjekk `journalctl -u bakeri-backend | grep auto-migrate`)
- [ ] Sentry mottar minst én test-event (kjør `raise Exception("sentry-test")` i et beskyttet endepunkt eller bruk `sentry-cli`)
- [ ] `scripts/backup.sh` har kjørt og produsert minst én fil i `/var/backups/bakeri`
- [ ] Cron eller systemd-timer for backup er aktiv (`systemctl list-timers | grep backup` eller `crontab -l`)

## 2. Sikkerhet

- [ ] Admin-passord for `jon.sigurdarson@advania.no` er endret fra default (`Advania3414`) — IKKE skip dette
- [ ] Alle gamle test-/demo-brukere er slettet (kun pilot-brukere finnes)
- [ ] `LOGIN_RATE_LIMIT` er satt fornuftig i `.env` (default 10 per 5 min — OK for produksjon)
- [ ] Etter 11 feil-login fra samme IP returneres HTTP 429
- [ ] HTTPS er aktivt (sertifikat gyldig minst 30 dager fram)
- [ ] `JWT_SECRET_KEY` er ikke default-verdien
- [ ] `httpx`-kallet til Susoft (`verify=False`) er enten oppgradert til `verify=True` eller dokumentert med begrunnelse

## 3. Login + multi-tenant isolasjon

- [ ] Logg inn som tenant A — ser kun tenant A sine kunder/produkter/ordre
- [ ] Logg inn som tenant B — ser kun tenant B sine kunder/produkter/ordre
- [ ] Forsøk å åpne en kunde-ID fra tenant A mens du er logget inn som tenant B → 404 eller 403
- [ ] Refresh-token virker (token blir fornyet uten ny login)
- [ ] Logout invaliderer token (eller token utløper innen forventet tid)

## 4. Kunder

- [ ] Hent kunder fra Susoft kjører uten feil (>0 kunder importert)
- [ ] Manuelt opprett kunde — vises i listen
- [ ] Rediger kunde (navn, adresse, leveringsdager) — endring lagres
- [ ] Sett kunde til inaktiv — skjules i ordreflyt

## 5. Produkter

- [ ] Hent produkter fra Susoft kjører — `created`/`updated` > 0
- [ ] Et produkt som er `active=false` i Susoft vises som **skjult** i vårt system
- [ ] Manuell skjuling i UI (`Eye/EyeOff`) holder seg ved neste sync (`is_active_overridden=true`)
- [ ] Ny `Edit2`-knapp åpner produksjons-modal og lagrer:
  - [ ] `batch_size`
  - [ ] `production_step`
  - [ ] `production_lead_minutes`
- [ ] Allergener vises korrekt på produktliste

## 6. Ordrer + maler

- [ ] Opprett ordre manuelt — kommer opp i ordreliste
- [ ] Ordre med fast mal (master template) genererer riktige linjer for valgt ukedag
- [ ] Endring av antall på en ordrelinje persisteres
- [ ] Cutoff-tid hindrer endring etter frist (test minst én ordre etter cutoff)
- [ ] Ordre kan markeres som levert
- [ ] Avbestilling/sletting krever bekreftelse

## 7. Produksjonsrapport

- [ ] Produksjonsrapport for i morgen viser korrekt antall pr. produkt
- [ ] `batch_size` brukes til å runde opp produksjon
- [ ] Filter på `production_step` virker (kun produkter for valgt stasjon)
- [ ] Eksport / utskrift gir lesbart format

## 8. Susoft-integrasjon end-to-end

- [ ] Synkronisering kjører automatisk på rute (cron / scheduler)
- [ ] Manuell `Sync nå`-knapp svarer innen 30 sek
- [ ] Sync-feil logges som alert (sjekk `alerts`-tabell)
- [ ] Susoft-passord/token er lagret kryptert (`crypto_utils.encrypt`)

## 9. Drift / observability

- [ ] Sentry-dashboard viser deploy-release-tag
- [ ] `journalctl -u bakeri-backend --since "1 hour ago"` har ingen `ERROR`-linjer som ikke er kjent/akseptert
- [ ] Disk-bruk på server > 20 % ledig
- [ ] Backup gjenoppretting er testet minst én gang (kopier siste backup til lokal maskin og last opp i SQLite-browser eller `psql`)

## 10. Brukervennlighet (med pilotbruker)

- [ ] Pilotbruker klarer å logge inn uten hjelp
- [ ] Pilotbruker forstår dashboard på under 2 min
- [ ] Pilotbruker klarer å registrere én ordre uten hjelp
- [ ] Pilotbruker kan endre et produkts batch_size uten hjelp
- [ ] Tilbakemeldinger noteres her: `__________`

---

## Sign-off

| Rolle              | Navn | Dato | Signatur |
|--------------------|------|------|----------|
| Teknisk ansvarlig  |      |      |          |
| Pilot-bruker       |      |      |          |
| Produkteier        |      |      |          |

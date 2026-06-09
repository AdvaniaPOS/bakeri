# Lampeland Bakeri - Ordresystem

Lampeland Bakeri Ordresystem er et B2B bestillingssystem for faste leveringer til bedriftskunder, med FastAPI-backend, React/Vite-frontend, Celery-jobber og integrasjon mot Susoft.

README-en er prosjektets korte oversikt. For detaljert funksjonsbeskrivelse og arkitektur, se dokumentene under.

## Status per juni 2026

| Område | Status | Kort forklaring |
|---|---|---|
| Ruteplanlegging og levering | Klar for test | Rute-modell, API, kundetildeling og adminside finnes. |
| Produksjonsrapporter | Klar for test | Dagsrapport, ukeoversikt, batch-plan og PDF-endepunkter finnes. |
| Ordreflyt og cutoff | Klar for test | Cutoff-logikk og ordrelåsing er implementert i backend. |
| Susoft-synkronisering | Satt i gang | Sync og adminstøtte finnes, men observabilitet bør styrkes. |
| Sikkerhet og MFA | Klar for test | Roller, tenant-scope, refresh tokens og MFA-støtte finnes. |
| Drift og helse | Satt i gang | Celery-jobber, statusendepunkter og innstillinger finnes. |

## Hva systemet gjør i dag

- Vedlikeholder kunder, produkter, priser og ukentlige bestillingsmaler.
- Genererer fremtidige ordrer automatisk basert på maler og leveringsregler.
- Låser ordre ved cutoff og hindrer endringer etter frist.
- Synkroniserer kunde-, produkt- og ordredata mot Susoft.
- Bygger produksjonsrapporter, batch-planer, pakklister og kjørelister.
- Støtter ruteplanlegging, leveringsflyt, driver-visning og statusoppfølging.
- Bruker tenant-basert sikkerhet med roller og MFA-støtte.

## Prosjektstruktur

```text
app/
├── main.py
├── models.py
├── schemas.py
├── tasks.py
├── auth.py / auth_models.py
├── cutoff.py / time_utils.py
├── api/
│   ├── admin.py
│   ├── auth.py
│   ├── customers.py
│   ├── driver.py
│   ├── notifications.py
│   ├── orders.py
│   ├── overrides.py
│   ├── portal.py
│   ├── pricing.py
│   ├── production.py
│   ├── products.py
│   ├── reports.py
│   ├── routes.py
│   ├── susoft_sync.py
│   └── templates.py
└── services/
  └── susoft.py

frontend/src/
├── App.jsx
├── components/
├── contexts/
└── pages/
  ├── Dashboard.jsx
  ├── Customers.jsx
  ├── Orders.jsx
  ├── Templates.jsx
  ├── RoutesPage.jsx
  ├── ProductionReport.jsx
  ├── DeliveryList.jsx
  ├── Driver.jsx
  ├── Status.jsx
  ├── Settings.jsx
  └── portal/
```

## Viktige dokumenter

- [SYSTEMBESKRIVELSE.md](SYSTEMBESKRIVELSE.md): forretningsbeskrivelse, status, arbeidsflyt og videre planer.
- [ARCHITECTURE.md](ARCHITECTURE.md): målarkitektur og teknisk spesifikasjon, synkronisert med dagens implementasjonsstatus.
- [docs/UAT-CHECKLIST.md](docs/UAT-CHECKLIST.md): forslag til akseptanse- og verifikasjonspunkter.
- [docs/TRELLO_JIRA_OPPSETT.md](docs/TRELLO_JIRA_OPPSETT.md): oppsett for styringstavle og backlog.
- [docs/LEDEROVERSIKT_UTVIKLING.md](docs/LEDEROVERSIKT_UTVIKLING.md): kort ledervennlig utviklingsstatus.
- [docs/TEKNISK_ENDRINGSLOGG.md](docs/TEKNISK_ENDRINGSLOGG.md): forskjellen mellom opprinnelig målarkitektur og dagens implementasjon.

## Viktige flyter

### Ordregenerering

- Kundene har ukentlige maler med produkter, ukedager og antall.
- En planlagt jobb genererer ordrer frem i tid basert på malene.
- Helligdager, blokkerte datoer og leveringsregler påvirker hvilke ordrer som faktisk opprettes.

### Cutoff og levering

- Ordreendringer stoppes når cutoff er passert.
- Ordre går gjennom en statusflyt fra utkast til levering.
- Samme ordredatasett brukes til produksjon, pakking og distribusjon.

### Produksjon og rapportering

- Dagsrapport viser hva som skal produseres for valgt dato.
- Ukeoversikt og batch-plan gir bedre planlegging i bakeriet.
- PDF-endepunkter brukes for utskrift av produksjons- og leveringsgrunnlag.

## Viktige API-områder

- `customers`, `products`, `pricing`, `templates` og `orders` for kjerneflyten.
- `routes` og `reports` for levering, produksjon og distribusjon.
- `admin`, `susoft_sync`, `notifications` og `driver` for drift og operasjonell støtte.
- `auth` og `portal` for sikkerhet og kundetilgang.

## Planlagte og aktive forbedringer

1. Verifisere ende-til-ende flyt for ruter, produksjon, cutoff og pakksedler.
2. Gjøre Susoft-sync, retry og driftsfeil mer synlig for admin og ledelse.
3. Ferdigstille prislogikk med gyldig fra dato og bedre audit-spor.
4. Bruke ledertavle og statusrapport fast i utviklingsoppfølgingen.

## Oppsett lokalt

### Forutsetninger

- Python 3.11+
- PostgreSQL eller SQLite for utvikling
- Redis for Celery
- Node.js for frontend

### Installer backend

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Start backend og jobber

```powershell
uvicorn app.main:app --reload
celery -A app.tasks worker --loglevel=info
celery -A app.tasks beat --loglevel=info
```

### Start frontend

```powershell
cd frontend
npm install
npm run dev
```

## License

Proprietary - Lampeland Bakeri

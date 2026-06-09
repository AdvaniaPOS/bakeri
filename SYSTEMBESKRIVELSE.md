# Lampeland Bakeri - Ordresystem

## Systembeskrivelse

### Hva er dette systemet?

Lampeland Bakeri Ordresystem er et **B2B bestillingssystem** designet for å automatisere håndtering av faste leveringer til bedriftskunder. Systemet erstatter manuelle bestillinger via telefon/SMS med en automatisert løsning som genererer ordrer basert på kundens ukentlige bestillingsmønster.

Dokumentet beskriver både **målbildet for løsningen**, **hva som faktisk er implementert per juni 2026**, og **hva som er planlagt videre**. Dette er viktig fordi systemet nå er kommet forbi ren idéfase: flere kjernefunksjoner finnes i kodebasen, mens andre deler fortsatt er under verifisering eller videreutvikling.

---

## Status per juni 2026

| Område | Status | Hva som er gjort |
|---|---|---|
| Ruteplanlegging og levering | Klar for test | Rute-modell, route-API, kundetildeling, postnummerregler og ruteside i admin finnes. |
| Produksjonsrapporter | Klar for test | Dagsrapport, ukeoversikt, batch-plan og PDF-generering finnes. |
| Ordreflyt og cutoff | Klar for test | Cutoff-logikk og låsing av ordre er implementert i backend og brukes også i portal-/ordrelogikk. |
| Susoft-synkronisering | Satt i gang | Sync-endepunkter, connection test og bakgrunnsjobber finnes, men operativ synlighet og feilhåndtering bør forbedres videre. |
| Sikkerhet og MFA | Klar for test | Roller, tenant-isolasjon, refresh tokens og støtte for e-post/TOTP-basert MFA finnes. |
| Drift og overvåking | Satt i gang | Celery-jobber, admin-status, helseendepunkter og tenant-innstillinger finnes. |
| Lederstyring og rapportering | Prioritert | Tavlestruktur, backlog og lederoversikter er definert, men må brukes aktivt i oppfølgingen. |

### Hva som ser levert ut nå

- Ruter i datamodell og API.
- Produksjonsrapport per dag og uke.
- Batch-plan og PDF-visninger for produksjon og levering.
- Cutoff-logikk for ordreendringer.
- Status- og adminfunksjoner for drift.
- MFA-grunnlag og rollebasert tilgang.

---

## Hovedfunksjoner

### 🥐 Abonnementsordrer (Maler)
Hver kunde har en **ukentlig mal** som definerer hva de ønsker levert på hver ukedag:

| Dag | Produkt | Antall |
|-----|---------|--------|
| Mandag | Kneippbrød | 10 stk |
| Mandag | Rundstykker | 20 stk |
| Tirsdag | Kneippbrød | 8 stk |
| Onsdag | Kneippbrød | 10 stk |
| ... | ... | ... |

Disse malene gjentar seg automatisk uke etter uke.

### 📅 Automatisk Ordregenerering
Systemet genererer ordrer **14-60 dager frem i tid** (konfigurerbart per kunde):

- Daglig jobb (kl. 02:00) sjekker fremtidige datoer
- Oppretter ordrer basert på kundens mal
- Tar hensyn til helligdager og kundens lukkede datoer (ferie, etc.)
- Ordrer kan justeres manuelt før de låses

### 🔒 Låsing av Ordrer
**Kl. 10:00 dagen før levering** låses alle ordrer:

- Ingen flere endringer mulig
- Ordrer synkroniseres til Susoft POS for fakturering
- Produksjonsrapport genereres automatisk

### 💰 Kundetilpassede Priser
Hver kunde kan ha egne priser som avviker fra standardpris:

- Priser kan settes med **gyldig fra dato**
- Når pris endres, oppdateres alle fremtidige ordrer automatisk
- Full sporbarhet av prisendringer

### 🚚 Ruteplanlegging
Kunder organiseres i **leveringsruter**:

- Ruter har definerte leveringsdager (f.eks. Man-Fre)
- Kunder sorteres i leveringsrekkefølge per rute
- Google Maps-integrasjon for navigasjon
- Kjøreliste med pakksedler for sjåføren

### 📊 Produksjonsrapporter
Daglig oversikt for bakerne:

- Totalt antall av hvert produkt som skal bakes
- Gruppert etter produktkategori
- Kan skrives ut eller vises på skjerm
- Ukeoversikt for planlegging

---

## Systemkomponenter

### Backend (API)
- **FastAPI** (Python) - REST API
- **SQLAlchemy** - Database ORM
- **Celery** - Automatiserte bakgrunnsjobber
- **PostgreSQL/SQLite** - Database

### Frontend (Admin Panel)
- **React** + **Vite** - Moderne web-applikasjon
- **TailwindCSS** - Styling

### Integrasjoner
- **Susoft POS API** - Ordrer sendes hit for fakturering
- **Google Maps** - Ruteoptimalisering

---

## Brukergrensesnitt

### Navigasjon

| Side | Formål |
|------|--------|
| **Dashboard** | Oversikt, statistikk, varsler |
| **Produkter** | Liste over alle bakervarer |
| **Kunder** | Kundeadministrasjon |
| **Bestillinger** | Se og endre ordrer |
| **Maler** | Redigere kundens ukentlige bestillinger |
| **Ruter** | Administrere leveringsruter |
| **Produksjon** | Daglig/ukentlig produksjonsrapport |
| **Kjøreliste** | Sjåførens leveringsliste |
| **Innstillinger** | Helligdager, varsler, sync-status |

---

## Dataflyt

```
┌─────────────────────────────────────────────────────────────┐
│                    LAMPELAND BAKERI                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  1. MASTER TEMPLATE (Ukentlig mal per kunde)                │
│     Kunde A: Man-Fre, 10x Kneipp, 20x Rundstykker          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ (Automatisk generering kl. 02:00)
┌─────────────────────────────────────────────────────────────┐
│  2. ORDRER (Genereres 14-60 dager frem)                     │
│     [DRAFT] → [CONFIRMED] → [READY_FOR_DELIVERY]           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ (Sync ved endringer + ved låsing kl. 10:00)
┌─────────────────────────────────────────────────────────────┐
│  3. SUSOFT POS                                              │
│     Mottar ordre for fakturering                            │
│     isForInvoicing: true                                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  4. LEVERING                                                │
│     Produksjonsrapport → Baking → Kjøreliste → Levering    │
└─────────────────────────────────────────────────────────────┘
```

---

## Hvordan systemet fungerer i dag

### 1. Grunndata og maler
Kunder og produkter vedlikeholdes i systemet og kan synkroniseres fra Susoft. Hver kunde kan ha en aktiv ukentlig bestillingsmal som beskriver hvilke varer som normalt skal leveres på hvilke ukedager.

### 2. Automatisk ordregenerering
En planlagt Celery-jobb genererer ordrer frem i tid basert på:

- kundens ukentlige mal
- kundens `order_lead_days`
- helligdager og blokkerte datoer
- produkt- og leveringsregler

Ordrene opprettes som egne ordreobjekter i databasen og kan deretter behandles videre i admin, portal og sync.

### 3. Ordreflyt og statuser
Ordrene går gjennom en tydelig statusflyt, typisk:

`DRAFT -> CONFIRMED -> READY_FOR_DELIVERY -> IN_TRANSIT -> DELIVERED`

Kansellerte ordrer markeres som `CANCELLED`. Når en ordre er synkronisert og klar for levering, brukes statusene videre i rapportering og leveringsflyt.

### 4. Cutoff og låsing
Cutoff håndteres i kode og beregnes per leveringsdato. Når cutoff er passert:

- ordinære endringer stoppes
- ordre markeres som låst
- systemet kan stemple låsetidspunkt via planlagt jobb
- admin-overstyring kan brukes der det er nødvendig

Dette gjelder både i adminflyt og i kundeportalen.

### 5. Produksjon og levering
Når ordrene finnes i systemet, brukes de til å bygge:

- dagsrapport for produksjon
- ukeoversikt
- batch-plan for produksjonsstasjoner
- pakklister og kjørelister
- Google Maps-lenker for ruter

Dette gjør at samme ordredatasett brukes både til baking, pakking og distribusjon.

### 6. Susoft og drift
Susoft-integrasjonen brukes til:

- henting av kunde- og produktgrunnlag
- sending av ordrer til fakturering
- connection test og statusoppfølging
- retry av feilede synkroniseringer

Driftssiden inneholder status, innstillinger og admin-funksjoner som gjør det mulig å følge med på systemhelse og avvik.

### 7. Sikkerhet og tilgang
Løsningen er tenant-basert og støtter ulike roller, blant annet super-admin, tenant-admin, manager, driver og kundeportalbruker. Innlogging bruker JWT/refresh tokens, og det finnes støtte for MFA via e-postkode eller TOTP.

---

## API Endepunkter

Dette er de viktigste endepunktene i løsningen slik den ser ut nå. Listen er representativ, ikke uttømmende.

### Kunder og produkter
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/customers` | Liste kunder med filtre |
| POST | `/api/v1/customers` | Opprett kunde |
| GET | `/api/v1/customers/{id}` | Hent kunde |
| PATCH | `/api/v1/customers/{id}` | Oppdater kunde |
| GET | `/api/v1/products` | Liste produkter |
| POST | `/api/v1/products` | Opprett produkt |
| GET | `/api/v1/products/{id}` | Hent produkt |
| PATCH | `/api/v1/products/{id}` | Oppdater produkt |

### Ordrer og maler
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/orders` | Liste ordrer med filtre |
| GET | `/api/v1/orders/by-date/{date}` | Hent ordrer for dato |
| POST | `/api/v1/orders` | Opprett manuell ordre |
| PATCH | `/api/v1/orders/{id}/lines/{line_id}` | Endre ordrelinje |
| POST | `/api/v1/orders/{id}/confirm` | Bekreft ordre |
| POST | `/api/v1/orders/generate-from-template` | Generer ordre fra mal |
| GET | `/api/v1/templates` | Liste maler |
| GET | `/api/v1/templates/{id}/matrix` | Hent matrisevisning for mal |
| PUT | `/api/v1/templates/{id}/matrix` | Oppdater matrisevisning |
| POST | `/api/v1/templates/{id}/duplicate` | Kopier mal |

### Ruter og levering
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/routes` | Liste ruter |
| POST | `/api/v1/routes` | Opprett rute |
| GET | `/api/v1/routes/{id}` | Hent rute med kunder |
| POST | `/api/v1/routes/{id}/assign-customers` | Tildel kunder til rute |
| GET | `/api/v1/routes/{id}/orders/{delivery_date}` | Hent ordrer per rute og dato |
| GET | `/api/v1/routes/{id}/postal-rules` | Liste postnummerregler |
| POST | `/api/v1/routes/{id}/postal-rules` | Opprett postnummerregel |

### Rapporter og PDF
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/reports/production/{target_date}` | Produksjonsrapport per dag |
| GET | `/api/v1/reports/production-batches/{target_date}` | Batch-plan per dag |
| GET | `/api/v1/reports/production-week` | Ukeoversikt |
| GET | `/api/v1/reports/delivery-list/{route_id}/{target_date}` | Kjøreliste |
| GET | `/api/v1/reports/route-packing-slips/{route_id}/{target_date}` | Pakksedler per rute |
| GET | `/api/v1/reports/pdf/production/{target_date}` | Produksjonsrapport som PDF |
| GET | `/api/v1/reports/pdf/packing-list/{target_date}` | Pakkeliste som PDF |
| GET | `/api/v1/reports/pdf/delivery-list/{route_id}/{target_date}` | Kjøreliste som PDF |

### Admin, drift og synk
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/admin/status` | Systemstatus og nøkkeltall |
| GET/POST | `/api/v1/admin/test-connection` | Test Susoft-tilkobling |
| POST | `/api/v1/admin/sync/customers` | Synk kunder fra Susoft |
| POST | `/api/v1/admin/sync/products` | Synk produkter fra Susoft |
| GET/PUT | `/api/v1/admin/settings` | Hent og oppdater innstillinger |
| GET/PUT | `/api/v1/admin/susoft-config` | Hent og oppdater Susoft-konfigurasjon |

---

## Automatiserte Jobber (Celery)

| Jobb | Tidspunkt | Beskrivelse |
|------|-----------|-------------|
| `generate_orders_for_all_customers` | Daglig 02:00 | Genererer ordrer frem i tid basert på aktive maler |
| `sync_pending_orders` | Hver 30. min | Synkroniserer nye og endrede ordrer til Susoft |
| `apply_cutoff_locks` | Daglig 10:00 | Stempler og vedlikeholder cutoff-låser |
| `retry_failed_syncs` | Daglig 06:00 | Kjører ny synk på tidligere feilede ordrer |
| `sync_from_susoft` | Daglig 04:00 | Henter kunde- og produktdata fra Susoft |
| `process_scheduled_price_changes` | Daglig 00:05 | Oppdaterer fremtidige ordrer ved planlagte prisendringer |

---

## Sikkerhet og Audit

### Dagens sikkerhetsmodell

Løsningen er bygd som en tenant-basert plattform der hver kundeorganisasjon har egne data og egne brukere. Tilgang styres med roller som blant annet:

- `SUPER_ADMIN`
- `TENANT_ADMIN`
- `MANAGER`
- `DRIVER`
- `VIEWER`
- `CUSTOMER_PORTAL`

Innlogging håndteres med access tokens og refresh tokens. Systemet støtter også tofaktorautentisering via:

- e-postkode
- TOTP/autentiseringsapp

MFA-støtten er på plass i modellen og innloggingsflyten, men bør fortsatt verifiseres ende-til-ende for alle administrative brukerroller.

### Audit Trail
Alle endringer logges med:
- Hvem gjorde endringen
- Tidspunkt
- Hva ble endret (gamle vs nye verdier)
- Ved sletting: Obligatorisk årsak

### Slette-kategorier
- `DUPLICATE` - Duplikat oppføring
- `MISTAKE` - Feilregistrering
- `CUSTOMER_REQUEST` - Kundens ønske
- `BUSINESS_CLOSED` - Bedrift nedlagt
- `TEST_DATA` - Testdata
- `OTHER` - Annet (krever forklaring)

---

## Feilhåndtering

### Susoft Sync Feil
Når sync feiler:
1. Ordren markeres som `FAILED`
2. Automatisk retry etter 60 minutter
3. Maks 3 forsøk
4. Ved vedvarende feil: Admin-varsling

I dagens løsning finnes også egne status- og adminendepunkter for å teste Susoft-tilkobling og følge opp synkroniseringsstatus. Videre arbeid bør gjøre denne delen enda tydeligere for drift og ledelse.

### Panikk-knapp 🚨
For nødsituasjoner (f.eks. leverandørsvikt):
- Kanseller alle ordrer for en dato med ett klikk
- Krever obligatorisk årsak
- Full audit trail
- Varsler berørte kunder (fremtidig funksjon)

---

## Planer for videre utvikling

Følgende områder bør prioriteres videre i neste utviklingsfase:

### 1. Verifisering av det som allerede er bygget

Mye av funksjonaliteten finnes allerede i kodebasen, men bør demonstreres og verifiseres i faktisk arbeidsflyt før det rapporteres som fullt levert. Dette gjelder spesielt:

- ruteplanlegging
- produksjonsrapporter
- cutoff og ordrelåsing
- MFA for adminbrukere
- pakksedler og kjørelister

### 2. Bedre synlighet rundt drift og synk

Susoft-integrasjonen er kritisk for fakturering og operativ trygghet. Videre arbeid bør derfor prioritere:

- tydeligere sync-status i admin
- bedre oversikt over retry og feil
- mer ledervennlige statusbilder
- klarere driftsrutiner ved avvik

### 3. Videreutvikling av prislogikk og audit

Kundetilpassede priser og historikk er sentralt for korrekt fakturering. Neste steg er:

- ferdigstille og verifisere prisendringer med gyldig fra dato
- sikre konsekvent oppdatering av fremtidige ordrer
- standardisere audit trail for bedre sporbarhet

### 4. Lederstyring og rapportering

For å gjøre utviklingen enklere å følge opp bør prosjektet bruke tavle og lederrapport aktivt. Det innebærer:

- fast ukentlig ledergjennomgang
- tydelig prioritering av maks 3 hovedsaker om gangen
- demonstrasjon av saker som står i `Klar for test`
- bevisst flytting av saker til `Ferdig` først etter verifikasjon

---

## Miljøvariabler

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost/lampeland_bakeri

# Susoft API
SUSOFT_BASE_URL=https://api.susoft.com:4443
SUSOFT_USERNAME=...
SUSOFT_PASSWORD=...
SUSOFT_SHOP_URL_KEY=...

# Celery/Redis
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Frontend
VITE_API_BASE_URL=http://localhost:8000
```

---

## Kom i gang

### Backend
```bash
# Installer avhengigheter
pip install -r requirements.txt

# Start API-server
uvicorn app.main:app --reload

# Start Celery worker (separat terminal)
celery -A app.tasks worker --loglevel=info

# Start Celery beat (for scheduled tasks)
celery -A app.tasks beat --loglevel=info
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### API Dokumentasjon
Åpne http://localhost:8000/docs for Swagger UI.

---

## Versjon

**Systemstatus oppdatert:** Juni 2026

Dokumentet beskriver en løsning som er delvis i produksjonsnær fase og delvis under videre verifisering og utvikling.

Utviklet for Lampeland Bakeri.

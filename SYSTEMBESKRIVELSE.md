# Lampeland Bakeri - Ordresystem

## Systembeskrivelse

### Hva er dette systemet?

Lampeland Bakeri Ordresystem er et **B2B bestillingssystem** designet for å automatisere håndtering av faste leveringer til bedriftskunder. Systemet erstatter manuelle bestillinger via telefon/SMS med en automatisert løsning som genererer ordrer basert på kundens ukentlige bestillingsmønster.

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
**Kl. 15:00 dagen før levering** låses alle ordrer:

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
                              ▼ (Sync ved endringer + ved låsing kl. 15:00)
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

## API Endepunkter

### Kunder
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/customers` | Liste alle kunder |
| POST | `/api/v1/customers` | Opprett ny kunde |
| GET | `/api/v1/customers/{id}` | Hent kunde |
| PUT | `/api/v1/customers/{id}` | Oppdater kunde |
| DELETE | `/api/v1/customers/{id}` | Slett kunde |

### Produkter
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/products` | Liste alle produkter |
| POST | `/api/v1/products` | Opprett nytt produkt |
| GET | `/api/v1/products/{id}` | Hent produkt |
| PUT | `/api/v1/products/{id}` | Oppdater produkt |

### Ordrer
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/orders` | Liste ordrer (filtrerbar) |
| POST | `/api/v1/orders` | Opprett ny ordre |
| GET | `/api/v1/orders/{id}` | Hent ordre med linjer |
| PUT | `/api/v1/orders/{id}` | Oppdater ordre |
| DELETE | `/api/v1/orders/{id}` | Slett ordre |

### Maler
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/templates` | Liste maler |
| GET | `/api/v1/templates/customer/{id}` | Hent kundens mal |
| PUT | `/api/v1/templates/{id}` | Oppdater mal |
| POST | `/api/v1/templates/{id}/items` | Legg til produktlinje |

### Ruter
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/routes` | Liste alle ruter |
| POST | `/api/v1/routes` | Opprett ny rute |
| GET | `/api/v1/routes/{id}` | Hent rute med kunder |
| POST | `/api/v1/routes/{id}/assign-customers` | Tildel kunder til rute |

### Rapporter
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/reports/production/{dato}` | Produksjonsrapport |
| GET | `/api/v1/reports/production-week` | Ukeoversikt |
| GET | `/api/v1/reports/delivery-list/{rute_id}/{dato}` | Kjøreliste |
| GET | `/api/v1/reports/packing-slip/{ordre_id}` | Pakkseddel |

### Synkronisering
| Metode | Endepunkt | Beskrivelse |
|--------|-----------|-------------|
| GET | `/api/v1/sync/status` | Sync-status oversikt |
| POST | `/api/v1/sync/customers` | Synk kunder fra Susoft |
| POST | `/api/v1/sync/products` | Synk produkter fra Susoft |
| POST | `/api/v1/sync/orders` | Push ordrer til Susoft |

---

## Automatiserte Jobber (Celery)

| Jobb | Tidspunkt | Beskrivelse |
|------|-----------|-------------|
| `generate_orders_task` | Daglig 02:00 | Genererer ordrer for fremtidige datoer |
| `sync_orders_to_susoft` | Hver 30 min | Synker nye/endrede ordrer til Susoft |
| `lock_orders_cutoff` | Daglig 15:00 | Låser ordrer for neste dag |
| `sync_customers_from_susoft` | Daglig 04:00 | Oppdaterer kundedata |
| `sync_products_from_susoft` | Daglig 04:30 | Oppdaterer produktdata |

---

## Sikkerhet og Audit

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

### Panikk-knapp 🚨
For nødsituasjoner (f.eks. leverandørsvikt):
- Kanseller alle ordrer for en dato med ett klikk
- Krever obligatorisk årsak
- Full audit trail
- Varsler berørte kunder (fremtidig funksjon)

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

**v1.0.0** - April 2026

Utviklet for Lampeland Bakeri.

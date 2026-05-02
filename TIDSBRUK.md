# Tidsbruk – Lampeland Bakeri Ordresystem

**Prosjekt:** Lampeland Bakeri – Ordre- og produksjonssystem
**Periode:** 16. mars 2026 – 2. mai 2026 (≈ 6,5 uker)
**Total tidsbruk:** **190 timer**
**Utvikler:** Jon Sigurdarson, Advania
**Kunde:** Lampeland Bakeri
**Plattform:** poshub.no (multi-tenant SaaS)

---

## Sammendrag

| Kategori | Timer | Andel |
|---|---:|---:|
| 1. Behovsanalyse og kundedialog | 18 | 9,5 % |
| 2. Domeneforståelse og research | 14 | 7,4 % |
| 3. Arkitektur og design | 12 | 6,3 % |
| 4. Backend-utvikling | 48 | 25,3 % |
| 5. Frontend-utvikling | 42 | 22,1 % |
| 6. Susoft-integrasjon | 18 | 9,5 % |
| 7. Deploy, drift og infrastruktur | 12 | 6,3 % |
| 8. Testing og kvalitetssikring | 10 | 5,3 % |
| 9. Bugfix, UX-polish og iterasjoner | 10 | 5,3 % |
| 10. Dokumentasjon og prosjektstyring | 6 | 3,2 % |
| **SUM** | **190** | **100 %** |

---

## 1. Behovsanalyse og kundedialog – 18 t

| Oppgave | Timer |
|---|---:|
| Oppstartsmøte med Lampeland Bakeri | 3 |
| Befaring og observasjon av dagens arbeidsflyt | 4 |
| Kartlegging av smertepunkter (manuelt arbeid, telefon-/SMS-bestillinger) | 3 |
| Kravspesifikasjon (roller, brukere, ordreflyt, leveringsruter) | 4 |
| Oppfølgingsmøter underveis | 3 |
| Avklaring av cutoff-regler og leveringsdager | 1 |

## 2. Domeneforståelse og research – 14 t

| Oppgave | Timer |
|---|---:|
| Bakeriproduksjon: lead times, batch-størrelser, produksjonssteg | 4 |
| Susoft API-dokumentasjon (1300+ linjer) – lese og forstå | 5 |
| Kartlegging av eksisterende ERP-flyt (Susoft som master) | 2 |
| Sammenligne lignende ordresystem-løsninger i markedet | 2 |
| Avklare GDPR/personvern for kundedata | 1 |

## 3. Arkitektur og design – 12 t

| Oppgave | Timer |
|---|---:|
| Teknologivalg (FastAPI + React + SQLAlchemy + Tailwind) | 2 |
| Multi-tenant-strategi (TenantMixin, scope, isolasjon) | 3 |
| Datamodell-design (ER-diagram, tabeller, relasjoner) | 3 |
| Auth-strategi (JWT, bcrypt, roller, refresh-tokens) | 2 |
| Deploy-arkitektur (Nginx, systemd, Postgres, backup) | 2 |

## 4. Backend-utvikling – 48 t

| Oppgave | Timer |
|---|---:|
| Database-modeller (Customer, Product, Order, Template, Route, Override, Cutoff, RolePermission, Tenant, User) | 10 |
| FastAPI-oppsett, dependency injection, middleware | 4 |
| Auth-modul (registrering, login, JWT, brute-force-beskyttelse, rate-limit) | 6 |
| Kunde-API (CRUD, bulk, filter, override) | 4 |
| Produkt-API (CRUD, kategorier, aktiv/inaktiv, override) | 4 |
| Ordre-API (opprett, oppdater, statusflyt, validering) | 6 |
| Template-API (matrise, ukentlige bestillinger) | 3 |
| Pricing- og override-logikk (per kunde/produkt) | 3 |
| Cutoff- og lead-day-logikk | 2 |
| Reports-API (produksjon, levering, ruter) | 3 |
| Tenant-admin og rolle-styring | 3 |

## 5. Frontend-utvikling – 42 t

| Oppgave | Timer |
|---|---:|
| Vite + React + Tailwind v4 oppsett, Layout, navigasjon | 3 |
| AuthContext, login/registrering/protected routes | 3 |
| Dashboard | 2 |
| Orders-side (liste, filter, detaljvisning, redigering) | 5 |
| NewOrder-side (kunde-/produktvalg, kalender, validering) | 5 |
| Customers-side (liste, søk, redigering, override-modal) | 4 |
| Products-side (liste, kategorier, aktiv/inaktiv, redigering) | 4 |
| Templates + TemplateMatrix (ukentlig bestillingsmønster) | 4 |
| DeliveryList + RoutesPage (leveringsruter) | 3 |
| ProductionReport (produksjonsark for bakeren) | 3 |
| Settings (sync, brukere, system) | 2 |
| TenantsAdmin (admin-panel) | 2 |
| Felles komponenter (Pagination, SearchInput, QuickOverrideModal) | 2 |

## 6. Susoft-integrasjon – 18 t

| Oppgave | Timer |
|---|---:|
| API-klient (auth, paginering, error handling) | 4 |
| Kunde-sync (initial import + delta) | 3 |
| Produkt-sync (initial import + delta) | 3 |
| Edge cases (Susoft `active` som lyver, dedupe, tom respons) | 4 |
| Audit- og probe-script for diagnose | 2 |
| Manuell sync fra UI (Settings + susoft_sync API) | 2 |

## 7. Deploy, drift og infrastruktur – 12 t

| Oppgave | Timer |
|---|---:|
| Server-oppsett (Ubuntu, Python, Node, systemd-unit) | 2 |
| Nginx + Let's Encrypt (bakeri.poshub.no) | 2 |
| Postgres-migrering fra SQLite | 2 |
| Backup-strategi (daglig dump + retensjon) | 1 |
| Sentry-integrasjon (feilrapportering) | 1 |
| Auto-migrate ved oppstart (lifespan) | 1 |
| Deploy-script (git pull + restart) | 1 |
| Log-rotering og overvåking | 2 |

## 8. Testing og kvalitetssikring – 10 t

| Oppgave | Timer |
|---|---:|
| Pytest-oppsett (conftest, isolert SQLite per test) | 2 |
| 41 enhets- og integrasjonstester | 5 |
| Smoke-test for tenant-isolasjon | 1 |
| Manuell testing av kjernescenarioer | 2 |

## 9. Bugfix, UX-polish og iterasjoner – 10 t

| Oppgave | Timer |
|---|---:|
| Søkefelt – min 3 tegn, debounce, X/Esc/Enter | 2 |
| Pagineringskomponent og sidestørrelse | 1 |
| Status-filter (aktive / skjulte) på alle sider | 1 |
| Override-modal (rask prisendring) | 2 |
| Diverse småfeil og feilmeldinger | 2 |
| Tilgjengelighet (aria-label, tastaturnav.) | 1 |
| Dark mode / fargejustering | 1 |

## 10. Dokumentasjon og prosjektstyring – 6 t

| Oppgave | Timer |
|---|---:|
| ARCHITECTURE.md | 1 |
| README.md + scripts/README.md | 1 |
| KUNDEPITCH.md | 1 |
| SYSTEMBESKRIVELSE.md | 1 |
| UAT-dokument og brukerveiledning | 1 |
| Intern prosjektoppfølging og statusoppdateringer | 1 |

---

## Verdivurdering

| Måling | Verdi |
|---|---|
| Total tidsbruk | **190 timer** |
| Tilsvarende byråleveranse (uten AI) | 520–760 timer |
| Anslått byråpris | **400 000 – 800 000 NOK** |
| Effektiv timesats om byrå tok 600 000 NOK / 190 t | **≈ 3 150 NOK/t** |
| Plattformverdi (multi-tenant – kan selges til flere bakerier) | Ikke prissatt – betydelig |

## Hvorfor leveransen er rask

- **AI-assistert utvikling** for boilerplate (CRUD, schemas, modeller)
- **Erfaring** med tilsvarende stack (FastAPI, React, multi-tenant)
- **Dyp domene-kunnskap** om Susoft og bakeridrift redusert behovet for omarbeiding
- **Direkte kundedialog** – ingen mellomledd, færre misforståelser

## Hva leveransen inkluderer

- Komplett backend (FastAPI, 12+ moduler, JWT-auth, multi-tenant, rolle-styring)
- Komplett frontend (React + Tailwind, 14 sider, responsive)
- Susoft-integrasjon (toveis sync med edge case-håndtering)
- Produksjonsdrift (Postgres, backup, monitoring, deploy)
- 41 automatiserte tester
- Komplett dokumentasjon
- Multi-tenant arkitektur klar for ny kunde nr. 2, 3, 4 …

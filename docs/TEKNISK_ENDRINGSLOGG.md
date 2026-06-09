# Teknisk Endringslogg

## Formål

Dette dokumentet forklarer forskjellen mellom den opprinnelige målarkitekturen i prosjektet og det som faktisk er implementert i kodebasen per juni 2026.

Det er ikke en full historikk over alle commits. Målet er å gi teknisk og ledelsesmessig oversikt over hva som har flyttet seg fra plan til faktisk løsning.

---

## Kort oppsummert

Prosjektet startet med flere arkitekturskisser som beskrev planlagte moduler, API-er og frontend-sider. I dagens kodebase er flere av disse delene implementert, og noen områder er også bygget videre utover den opprinnelige skissen.

Det viktigste skillet er derfor ikke lenger mellom `planlagt` og `ikke planlagt`, men mellom:

- hva som allerede finnes i kode
- hva som er klart for test
- hva som fortsatt trenger videreutvikling eller bedre operativ synlighet

---

## 1. Ruter og levering

### Opprinnelig målarkitektur

- Egen route-modell.
- Eget route-API.
- Enkel ruteside i frontend.

### Dagens implementasjon

- `Route` er implementert i datamodellen.
- `Customer` er koblet til rute via `route_id`.
- `app/api/routes.py` finnes og støtter mer enn bare enkel CRUD.
- Postnummerregler for ruter er lagt til.
- Frontend-siden [frontend/src/pages/RoutesPage.jsx](frontend/src/pages/RoutesPage.jsx) finnes og inneholder administrasjon av ruter, kunder og regler.

### Arkitektonisk konsekvens

Dette området er ikke lenger et designmål, men en implementert del av systemet som primært trenger verifisering og operativ bruk.

---

## 2. Produksjonsrapporter

### Opprinnelig målarkitektur

- Daglig produksjonsrapport.
- Enkel ukeoversikt.
- Egen modell for produksjonssammendrag.

### Dagens implementasjon

- `app/api/reports.py` har dagsrapport per dato.
- Ukeoversikt er implementert.
- Batch-plan per produksjonsstasjon er lagt til.
- PDF-endepunkter for produksjon, pakkeliste og kjøreliste finnes.
- Frontend-siden [frontend/src/pages/ProductionReport.jsx](frontend/src/pages/ProductionReport.jsx) støtter flere visninger enn den opprinnelige skissen.

### Arkitektonisk konsekvens

Rapportering har utviklet seg fra en enkel aggregert rapport til en mer operativ del av systemet som støtter både produksjon og distribusjon.

---

## 3. Autentisering og sikkerhet

### Opprinnelig målarkitektur

- README beskrev autentisering som et senere steg.
- Sikkerhet var i større grad omtalt som behov enn som ferdig løsning.

### Dagens implementasjon

- Tenant-basert tilgangsmodell er implementert.
- Roller som `SUPER_ADMIN`, `TENANT_ADMIN`, `MANAGER`, `DRIVER`, `VIEWER` og `CUSTOMER_PORTAL` finnes.
- JWT og refresh tokens brukes i autentiseringsflyten.
- MFA-støtte finnes for både e-postkode og TOTP.
- Frontend har login-, register-, forgot-password- og reset-flow.

### Arkitektonisk konsekvens

Autentisering er ikke lenger bare planlagt. Hovedjobben videre er verifikasjon, herding og tydeligere driftsrutiner rundt adminbrukere og MFA.

---

## 4. Frontend og operativt grensesnitt

### Opprinnelig målarkitektur

- Admin-UI var omtalt som et fremtidig steg.
- Enkelte sider var beskrevet som nye filer som skulle lages.

### Dagens implementasjon

- Adminpanel finnes med sider for dashboard, kunder, produkter, ordrer, maler, ruter, produksjon, kjøreliste, status og innstillinger.
- Driver-visning finnes.
- Kundeportal finnes.
- Flere frontend-sider er mer funksjonsrike enn de opprinnelige skissene i arkitekturdokumentet.

### Arkitektonisk konsekvens

Frontend er gått fra planlagt flate til faktisk arbeidsverktøy. Dokumentasjonen må derfor beskrive status og modenhet, ikke bare designintensjon.

---

## 5. Susoft, admin og drift

### Opprinnelig målarkitektur

- Susoft ble beskrevet primært som ordreintegrasjon.
- Drift og oppfølging var enklere beskrevet.

### Dagens implementasjon

- Det finnes adminendepunkter for status, innstillinger, connection test og Susoft-konfigurasjon.
- Kunde- og produktsynk finnes.
- Celery-jobber finnes for ordregenerering, sync, retry, cutoff og prisendringer.
- Statusside i frontend finnes.

### Arkitektonisk konsekvens

Løsningen har fått et tydelig driftslag. Det som gjenstår er bedre observabilitet og mer ledervennlig status på sync og feil.

---

## 6. Navn og struktur som har endret seg

Noen viktige forskjeller mellom eldre spesifikasjon og dagens kode:

- Flere seksjoner i [ARCHITECTURE.md](../ARCHITECTURE.md) beskrev moduler som "mangler" selv om de nå finnes.
- Routes-siden er implementert som [frontend/src/pages/RoutesPage.jsx](frontend/src/pages/RoutesPage.jsx), ikke `Routes.jsx`.
- Rapportlaget er bredere enn den første skissen og inkluderer batch-plan og PDF-endepunkter.
- README beskrev tidligere autentisering og frontend som fremtidige steg; dette er nå endret fordi de allerede finnes i repoet.

---

## 7. Hva som fortsatt er målarkitektur eller videre arbeid

Dette er de viktigste områdene som fortsatt bør behandles som aktiv videreutvikling:

1. Verifisering av ruter, produksjonsrapporter, cutoff og pakksedler med reelle data.
2. Bedre observabilitet rundt Susoft-sync, retry og feiltilstander.
3. Ferdigstillelse og verifikasjon av prislogikk med gyldig fra dato.
4. Standardisering av audit-spor og ledervennlig statusrapportering.
5. Strammere operativ dokumentasjon for nødprosedyrer og avvikshåndtering.

---

## Sannhetskilder

Når dokumentasjon og kode avviker, bør disse brukes som prioritert sannhetskilde:

1. Kode i `app/` og `frontend/src/`
2. [SYSTEMBESKRIVELSE.md](../SYSTEMBESKRIVELSE.md)
3. [ARCHITECTURE.md](../ARCHITECTURE.md)
4. [README.md](../README.md)

Dette gjør det enklere å holde styringsdokumenter og teknisk dokumentasjon konsistente videre.
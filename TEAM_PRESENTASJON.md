# 🥐 Lampeland Bakeri Ordresystem
### Rask teamgjennomgang

---

## Intro

Lampeland Bakeri hadde en **manuell ordrehverdag** preget av telefon, SMS, eposter, manuell innlegging mot SuSoft. Det førte til  mye administrasjon for bakerisjefen.

Vi har bygget et **ordresystem** som automatiserer hele flyten — fra kundens faste ukemal, via produksjon og levering, til ferdig faktura i SuSoft. Systemet er ferdigutviklet, integrert og i drift på poshub.no.


---

## Hva er dette?

Et **B2B ordresystem** som automatiserer faste leveringer til bedriftskunder.
Erstatter telefon, SMS og lapper med ett samlet system — fra bestilling til fakturering.

---

## Hovedpunkter

### 1. 📋 Faste maler per kunde
- Hver kunde har en **ukentlig bestillingsmal** (hva, hvor mye, hvilken dag)
- Settes opp én gang → gjelder for alltid
- Kundespesifikke priser med gyldighetsdato

### 2. 🤖 Automatisk ordregenerering
- Daglig jobb (kl. 02:00) lager ordrer **14–60 dager frem i tid**
- Tar hensyn til **helligdager** og **kundens ferier**
- Manuelle justeringer mulig frem til lås

### 3. 🔒 Cutoff / låsing
- Ordrer låses **kl. 10:00 dagen før levering**
- Etter lås: ingen endringer, klar for produksjon og fakturering

### 4. 🍞 Produksjonsrapport
- Bakerne får eksakt antall per produkt hver morgen
- Gruppert etter kategori, kan skrives ut

### 5. 🚚 Ruter og kjøreliste
- Kunder organisert i leveringsruter med rekkefølge
- Sjåfør får kjøreliste + pakksedler på mobil
- Google Maps-integrasjon for navigasjon

### 6. 💸 Susoft-integrasjon
- Låste ordrer **synkroniseres automatisk** til Susoft POS
- Fakturering går riktig første gang
- Kundedata og produkter synkes begge veier

### 7. 👥 Flere brukerroller
- Admin, baker, sjåfør, kunde — hver med eget grensesnitt
- 2-faktor-autentisering for admin
- Multi-tenant (flere bakerier i samme system mulig)

---

## Teknisk stack (kort)

| Lag | Teknologi |
|-----|-----------|
| Backend | FastAPI (Python), SQLAlchemy, Celery |
| Database | PostgreSQL (prod) / SQLite (dev) |
| Frontend | React + Vite + TailwindCSS |
| Integrasjoner | Susoft POS, Google Maps, Resend (e-post) |

---

## Gevinster for bakeriet

- ⏱️ **Mindre tid** på telefon og manuell ordrehåndtering
- ✅ **Færre feil** — ingen glemte bestillinger eller feilpriser
- 📈 **Bedre oversikt** — produksjon, levering og fakturering på ett sted
- 😊 **Fornøyde kunder** — alt leveres riktig og i tide

---

## Diskusjon
- Hvilke kunder pilotere vi først?
- Trenger vi flere integrasjoner?
- Opplæring av baker / sjåfør?

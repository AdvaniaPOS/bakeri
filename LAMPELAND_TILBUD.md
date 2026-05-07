# Tilbud — Bakeri Ordresystem for Lampeland Bakeri

*Utarbeidet av Advania, mai 2026*

---

## Hva vi tilbyr Lampeland Bakeri

Et komplett ordre- og leveringssystem som automatiserer hverdagen fra
kundens bestilling til ferdig faktura i SuSoft. Systemet er allerede
ferdigutviklet, integrert mot SuSoft (aPOS), og kjører i drift.

### Konkret hjelp til Lampeland

**1. Slutt på manuell ordretaking**
- Faste kunder (butikker, kafeer, hytter, storkjøkken) får hver sin
  ukentlig bestillings-mal med produkt og antall pr. ukedag.
- Systemet genererer ordrene automatisk hver natt — ferdig flere uker
  fram i tid.
- Norske helligdager og lokale fridager (skoleferier, lokale stengninger)
  hopper systemet automatisk over.

**2. Sluttkundene bestiller selv via portal**
- Hver butikk/kafé får eget login og kan justere mengder fram til
  cutoff (typisk kl. 18:00 dagen før levering).
- Ser leveringsplan, historikk og faktura-status.
- Bakeriet slipper telefoner og SMS om småjusteringer.

**3. Produksjonsliste til bakeren hver morgen**
- Aggregert oversikt: "I morgen skal vi bake 245 kneippbrød,
  380 rundstykker..."
- Hensyntar batch-størrelser og produksjons-ledetid (deig-heving,
  gjær-tid osv.).
- Ingen overproduksjon, mindre svinn.

**4. Sjåfør-app på mobil**
- Optimalisert ruteliste med leveringsadresser i riktig rekkefølge.
- Bekrefter levering med ett trykk, registrerer retur og svinn på stedet.
- Gir kunden direkte oppdatert leveringsstatus.

**5. Direkte integrasjon mot SuSoft**
- Når bakeriet bekrefter en ordre, pushes den som ferdig faktura-grunnlag
  inn i SuSoft. Ingen dobbel innlegging.
- Kundespesifikke priser, mengderabatter og kampanjer respekteres.
- Faktureres samme dag → bedre likviditet.

**6. Full sporbarhet og sikkerhet**
- 2-faktor pålogging, rollebasert tilgang (bakerisjef, baker, sjåfør,
  kontor, sluttkunde).
- Audit-logg på alle endringer — hvem endret hva, når.
- Daglig backup, kryptert lagring av kredentialer.

---

## Tidsbesparelse for Lampeland (estimat)

Anta 25–40 faste kunder med 4–6 leveringsdager pr. uke:

| Oppgave | I dag (manuelt) | Med systemet | Spart pr. uke |
|---|---|---|---|
| Ta imot/registrere ordrer | 1,5–2 t/dag | 0–15 min | **8–10 t** |
| Legge ordrer inn i SuSoft | 30–45 min/dag | Auto | **3–5 t** |
| Lage produksjonsliste | 30 min/dag | Auto | **3 t** |
| Lage ruteark til sjåfør | 20 min/dag | Auto | **2 t** |
| Avstemme retur/svinn | 30 min/dag | I sjåfør-appen | **2 t** |
| Håndtere endringer/feil | 1 t/dag | 15 min | **4 t** |
| **Totalt** | | | **~22–26 t/uke** |

**~0,6 årsverk frigjort** = mer tid til produksjon, salg og nye kunder.

I tillegg:
- **Færre feilleveranser** → fornøyde kunder, færre kreditnotaer
- **Mindre svinn** → korrekt produksjonsmengde
- **Raskere fakturering** → bedre likviditet
- **Skalerbart** → 60 kunder krever ikke mer admin enn 30

---

## Pris

### Oppstart (engangs)

| Post | Pris |
|---|---|
| Oppsett av tenant, brukerkontoer og roller | 8 000,- |
| Import av kunde- og produktbase fra SuSoft | 6 000,- |
| Oppsett av bestillings-maler (inntil 30 kunder) | 12 000,- |
| Konfigurasjon av leveringsruter og cutoff-tider | 4 000,- |
| Opplæring (2 økter à 2 t — bakerisjef, kontor, sjåfør) | 8 000,- |
| Go-live-oppfølging første 2 uker | 4 000,- |
| **Sum oppstart** | **42 000,- eks. mva** |

*Tilleggskunder utover 30 ved oppstart: 300,- pr. kunde-mal.*

### Lisens (månedlig)

| Plan | Inkluderer | Pris/mnd |
|---|---|---|
| **Standard** | Inntil 40 sluttkunder, ubegrenset ordrer, sjåfør-app, kundeportal, SuSoft-integrasjon, daglig backup, e-post-support | **3 900,-** |
| **Pluss** | Som Standard + inntil 100 sluttkunder, prioritert support, telefon-support hverdager 08–16 | **5 900,-** |
| **Enterprise** | Ubegrenset, dedikert kontaktperson, SLA 99,5 %, månedlig driftsmøte | **fra 8 900,-** |

*Alle priser eks. mva. 12 mnd binding første år, deretter løpende
3 mnd oppsigelse.*

### Tillegg (valgfritt)

| Tjeneste | Pris |
|---|---|
| Tilpasninger / nye rapporter | 1 250,- pr. time |
| Ekstra opplæringsøkt | 1 800,- pr. økt |
| Migrering fra annet system | etter avtale |
| SMS-varsling til sluttkunder (per SMS) | 0,55 eks. mva |

---

## Inntjening for Lampeland

Med Standard-plan:
- Investering år 1: 42 000 + (12 × 3 900) = **88 800,- eks. mva**
- Frigjort tid år 1: ~22 t/uke × 50 uker × 350,- timekost = **~385 000,-**
- **Netto besparelse år 1: ~296 000,-**

Fra og med år 2 er kun lisens-kostnaden løpende (~47 000,-/år), så
besparelsen øker.

---

## Neste steg

1. Demo hos Lampeland — vi viser systemet live på en time.
2. Pilot med 5 kunder i 30 dager — vi kjører i parallell med dagens
   rutiner så dere ser effekten før dere bestemmer dere.
3. Full utrulling — typisk 2–3 uker fra signert avtale til daglig drift.

**Kontakt:** Advania — *[telefon/e-post]*

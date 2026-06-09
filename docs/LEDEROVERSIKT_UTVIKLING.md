# Lederoversikt - utviklingsstatus

Dato: 2026-06-08

Denne oversikten er laget for ledere som vil se reell fremdrift uten a lese kode. Vurderingen er basert pa kodegjennomgang i repoet, ikke full funksjonell test.

---

## Kort bilde

Prosjektet ser mer modent ut enn en ren idefase. Flere kjernefunksjoner finnes allerede i kodebasen, spesielt i backend, mens flere av dem bor flyttes fra `Satt i gang` til `Klar for test` eller `Ferdig` i styringstavlen.

Det viktigste ledelsen bor styre na er ikke bare ny utvikling, men verifikasjon, operativ synlighet og tydelig prioritering.

---

## Status per omrade

| Omrade | Status | Hva det betyr |
|---|---|---|
| Ruteplanlegging og levering | Klar for test | Datamodell, API og adminside for ruter finnes. Borde demonstreres med ekte kundedata. |
| Produksjonsrapporter | Klar for test | Dagsrapport, ukeoversikt, batch-plan og PDF-stotte finnes. Borde testes i faktisk arbeidsflyt. |
| Ordreflyt og cutoff | Klar for test | Cutoff-logikk og lasing finnes i backend og portalflyt. Trenger en kort funksjonell godkjenning. |
| Susoft-synkronisering | Satt i gang | Integrasjonen er omfattende, men ledervennlig oversikt over feil og retry bor forbedres. |
| Sikkerhet og MFA | Klar for test | MFA-stotte og sikkerhetsflyt ser bygget ut, men bor verifiseres for adminbrukere. |
| Drift og overvaking | Satt i gang | Bakgrunnsjobber og health checks finnes, men operativ overvaking bor gjores tydeligere. |
| Lederstatus og styring | Prioritert | Dokumentasjon og tavlegrunnlag finnes na, men det bor tas i bruk fast i ukentlig oppfolging. |

---

## Hva som ser levert ut na

- Ruter i datamodell og route-API.
- Produksjonsrapport per dag.
- Ukeoversikt og batch-plan for produksjon.
- Cutoff-logikk for ordreendringer.
- Status- og helsesider i adminpanelet.
- MFA-grunnlag i autentisering og frontend-loginflyt.

---

## Hva som bor prioriteres neste 2-3 uker

1. Verifisere alt som na kan flyttes til `Klar for test`, spesielt ruter, produksjon og cutoff.
2. Forbedre synlighet rundt Susoft-sync, retry og driftsfeil slik at ledelsen ser risiko tidligere.
3. Avklare prislogikk og audit trail som egne styringssaker med tydelig eier.
4. Dokumentere panic-cancel og andre driftsrutiner for avvikssituasjoner.
5. Innfore fast ukentlig ledergjennomgang basert pa tavlen, ikke pa losse notater.

---

## Beslutninger ledelsen bor ta

1. Hvem eier prioritering av saker i `Prioritert`?
2. Hvem kan godkjenne flytting fra `Klar for test` til `Ferdig`?
3. Hvilke 3 saker er viktigst a fa demonstrert neste uke?
4. Hvor ofte skal `Ferdig` flyttes til `Arkiv`?

---

## Anbefalt rapportering i mote

Bruk disse fire sporsmalene fast:

1. Hva er ferdig siden sist?
2. Hva star i fare for a stoppe opp?
3. Hva trenger ledelsesbeslutning na?
4. Hva er neste leveranse som kan demonstreres?

Dette gir bedre styring enn a snakke generelt om at prosjektet er "i gang".
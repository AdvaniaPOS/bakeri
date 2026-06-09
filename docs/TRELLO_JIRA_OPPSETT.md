# Trello/Jira-oppsett for Lampeland Bakeri

## Formål

Dette oppsettet er laget for at ledere skal kunne se:

- hva som er foreslått
- hva som er prioritert
- hva som er satt i gang
- hva som testes
- hva som er ferdigstilt
- hva som er avsluttet og arkivert

Oppsettet fungerer både i Jira og Trello. I Jira anbefales statusflyt, epics og dashboards. I Trello anbefales lister, labels og faste kortmaler.

---

## Anbefalt tavlestruktur

Bruk disse kolonnene/listene i denne rekkefølgen:

| Kolonne | Når brukes den | Hva ledelsen ser |
|---|---|---|
| `Ide` | Nye forslag, forbedringer, feil og ønsker | Hva som vurderes, men ikke er prioritert |
| `Avklart` | Saker som er beskrevet godt nok til å kunne prioriteres | Hva som er analysert og klart for beslutning |
| `Prioritert` | Godkjente saker som skal gjennomfores snart | Hva som ligger i neste bolge |
| `Satt i gang` | Aktiv utvikling er startet | Hva teamet jobber med akkurat na |
| `Blokkert` | Saker som stopper opp pa grunn av avhengigheter, avklaringer eller feil | Hvor risiko og forsinkelse ligger |
| `Klar for test` | Utvikling er ferdig og saken er klar for verifikasjon | Hva som kan kvalitetssikres na |
| `Test` | Saken er under funksjonell test, UAT eller intern gjennomgang | Hva som er naer produksjonsklart |
| `Ferdig` | Godkjent og levert | Hva som er levert med verdi |
| `Arkiv` | Eldre ferdige eller droppede saker som ikke lenger skal sta i aktiv tavle | Historikk uten stoy |

Hvis dere vil holde tavlen enklere, kan `Avklart` og `Prioritert` slas sammen. Hvis dere vil ha enda tydeligere styring for ledelsen, behold begge.

---

## Flytregler

Bruk disse reglene fast:

1. Alle nye saker starter i `Ide`.
2. En sak flyttes til `Avklart` nar problem, gevinst og omfang er beskrevet.
3. En sak flyttes til `Prioritert` nar ansvarlig leder har godkjent at den skal inn i plan.
4. En sak flyttes til `Satt i gang` nar utvikler faktisk har startet arbeidet.
5. En sak flyttes til `Blokkert` umiddelbart hvis den ikke kan drives videre.
6. En sak flyttes til `Klar for test` nar kode, dokumentasjon og egenkontroll er ferdig.
7. En sak flyttes til `Test` nar en annen person eller definert testrolle verifiserer leveransen.
8. En sak flyttes til `Ferdig` nar den er godkjent og klar i miljoet dere bruker som sannhetskilde.
9. En sak flyttes til `Arkiv` etter 2-4 uker i `Ferdig`, eller ved kvartalsvis opprydding.

---

## Hva hvert kort skal inneholde

Hvert kort eller issue bor ha disse feltene:

| Felt | Forklaring |
|---|---|
| `Tittel` | Kort og konkret, beskriv leveransen |
| `Type` | Epic, Story, Task, Bug, Drift, Forbedring |
| `Bakgrunn` | Hvorfor saken finnes |
| `Mal/onsket effekt` | Hva bedriften skal fa igjen |
| `Omfang` | Hva som er med og hva som ikke er med |
| `Akseptansekriterier` | Hvordan vi vet at saken er god nok |
| `Ansvarlig` | Eier av saken |
| `Testansvarlig` | Hvem som skal verifisere |
| `Prioritet` | Hoy, Medium, Lav |
| `Estimert innsats` | XS, S, M, L eller timer/dager |
| `Frist` | Nar saken bor vaere ferdig |
| `Avhengigheter` | Andre saker eller beslutninger som saken er avhengig av |
| `Risiko` | Hva som kan ga galt |
| `Statusnotat` | Kort oppdatering som ledelsen kan lese pa 20 sekunder |

---

## Kortmal for nye saker

Bruk denne teksten som standardmal i Jira-beskrivelse eller Trello-kort:

```text
Bakgrunn:
Hvorfor trenger vi dette?

Mal:
Hvilken verdi skal dette gi for drift, kunder eller ledelse?

Leveranse:
Hva skal faktisk bygges eller endres?

Omfang:
Inkludert:
- 

Ikke inkludert:
- 

Akseptansekriterier:
- 
- 
- 

Test:
Hvordan skal dette verifiseres?

Risiko/avhengigheter:
- 

Statusnotat til ledelsen:
En kort setning som forklarer hvor saken star.
```

---

## Definisjoner per status

### Ide
- Saken kan vaere kort beskrevet.
- Det er lov at detaljer mangler.
- Hensikt er synlighet, ikke oppstart.

### Avklart
- Problem og mal er tydelige.
- Det finnes minst ett utkast til akseptansekriterier.
- Saken er moden nok til at leder kan prioritere den.

### Prioritert
- Eier er satt.
- Forventet tidsrom er kjent.
- Saken kan tas inn i arbeid uten ny analyse.

### Satt i gang
- Arbeid er faktisk startet.
- Første tekniske retning er valgt.
- Kortet oppdateres minst en gang per uke.

### Blokkert
- Det star tydelig hva som blokkerer.
- Det star hvem som ma lose blokkeringen.
- Det star neste tidspunkt for oppfolging.

### Klar for test
- Utvikler har gjort egenkontroll.
- Dokumentasjon eller skjermbilder er lagt ved ved behov.
- Akseptansekriteriene er gjennomgaatt.

### Test
- En annen person eller definert testrolle verifiserer.
- Eventuelle avvik logges pa samme sak eller som underoppgaver.

### Ferdig
- Kravene er oppfylt.
- Ledere kan se konkret leveranse og effekt.
- Eventuell opplaering eller dokumentasjon er gjort.

### Arkiv
- Saken er ikke lenger del av aktiv rapportering.
- Ligger fortsatt tilgjengelig for sporbarhet.

---

## Labels og kategorier

Anbefalte labels:

| Label | Bruk |
|---|---|
| `backend` | API, database, jobbprosesser |
| `frontend` | Adminpanel og skjermbilder |
| `integrasjon` | Susoft, e-post, maps, eksterne tjenester |
| `ordre` | Ordregenerering, ordrelinjer, cutoff |
| `kunde` | Kundedata, favoritter, ruter, levering |
| `rapport` | Produksjonsrapport, kjorelister, oppfolging |
| `sikkerhet` | Innlogging, MFA, roller, rate limiting |
| `drift` | Deploy, logging, overvaking, backup |
| `bug` | Feil som ma rettes |
| `forbedring` | Kvalitetsforbedringer og optimalisering |
| `lederrapport` | Saker som er relevante i styringsmote |

Anbefalte prioriteter:

- `Hoy`: stopper drift, levering eller fakturering
- `Medium`: viktig for kvalitet, effektivitet eller synlighet
- `Lav`: nyttig, men ikke tidskritisk

---

## Anbefalte issue-typer

Hvis dere bruker Jira, sett opp disse issue-typene:

| Type | Nar den brukes |
|---|---|
| `Epic` | Storre leveranseomrader over flere uker |
| `Story` | Brukerverdi eller forretningsbehov |
| `Task` | Teknisk arbeid eller avgrenset leveranse |
| `Bug` | Feil som skal rettes |
| `Spike` | Kort analyse eller avklaring |
| `Drift` | Deploy, backup, miljo og overvaking |

Hvis dere bruker Trello, kan `Epic` vaere egne kort med sjekklister eller egne labels.

---

## Epics som passer dette systemet

Disse epicene matcher systembeskrivelsen og arkitekturen:

1. `Kunde- og produktmaster`
2. `Abonnementsmaler og ordregenerering`
3. `Ordreflyt og cutoff`
4. `Susoft-synkronisering`
5. `Ruteplanlegging og levering`
6. `Produksjonsrapporter`
7. `Sikkerhet og tilgangsstyring`
8. `Drift, logging og varsling`
9. `Adminpanel og brukeropplevelse`

---

## Forslag til første backlog

Under er et konkret startsatt med saker som kan legges rett inn i tavlen.

Statusene under er justert mot kodebasen slik den ser ut na, slik at tavlen blir mer troverdig for ledelsen. Dette er en grov statusvurdering basert pa kodefunn, ikke full funksjonell test.

| Tittel | Type | Anbefalt startstatus | Prioritet | Forklaring |
|---|---|---|---|---|
| Etablere route-modell og kundekobling | Story | `Ferdig` | Hoy | Ser implementert ut i datamodell og kundekobling |
| Lage API for ruter og kundetildeling | Story | `Ferdig` | Hoy | Eget route-API med CRUD og kundetildeling finnes |
| Bygge visning for ruter i adminpanelet | Story | `Klar for test` | Medium | Ruteside finnes i frontend, men bor verifiseres ende-til-ende |
| Generere daglig produksjonsrapport per dato | Story | `Ferdig` | Hoy | Eget rapportendepunkt og visning finnes |
| Lage ukeoversikt for produksjon | Task | `Klar for test` | Medium | Ukeoversikt finnes, men bor funksjonelt verifiseres |
| Forbedre oversikt over Susoft-sync-feil | Story | `Satt i gang` | Hoy | Viktig for fakturering og oppfolging |
| Lage tydelig statusside for sync og retry | Task | `Klar for test` | Medium | Statusside og helseendepunkter finnes, men bor kvalitetssikres |
| Fullfore order cutoff og lasing kl. 10 | Story | `Klar for test` | Hoy | Cutoff-logikk og planlagt jobb finnes i backend |
| Dokumentere panic-cancel-prosessen | Task | `Ide` | Medium | Viktig for driftssikkerhet ved avvik |
| Ferdigstille prislogikk med gyldig fra dato | Story | `Satt i gang` | Hoy | Sikrer korrekt kundepris og fremtidige ordre |
| Innfore dashboard for lederstatus | Story | `Prioritert` | Medium | Gir enkel oversikt over progresjon og risiko |
| Verifisere MFA og sikkerhetsflyt for adminbrukere | Task | `Klar for test` | Medium | Reduserer risiko i innlogging og tilgang |
| Etablere overvaking av bakgrunnsjobber | Drift | `Satt i gang` | Medium | Celery-jobber og health checks finnes, men bor strammes opp operativt |
| Rydde og standardisere audit trail for endringer | Forbedring | `Prioritert` | Medium | Viktig for sporbarhet og kontroll |
| Lage pakkseddel- og kjorelistevisning | Story | `Klar for test` | Medium | Rapporter og leveringsvisning finnes, men bor verifiseres med reelle data |

---

## Hvordan lese denne backloggen

For ledelsen anbefales disse to tolkningene:

- `Ferdig`: Funksjonen ser implementert ut og kan vises fram.
- `Klar for test`: Funksjonen finnes, men bor gjennom en kort UAT eller intern test for a bli troverdig rapportert som levert.

Dette er ofte mer nyttig enn a la alt sta som `Ide` eller `Satt i gang` naer mye allerede ligger i kodebasen.

---

## Neste styringsgrep

Hvis dere vil bruke tavlen aktivt fra denne uka, anbefales dette:

1. Flytt alle kodebaserte saker til statusene over.
2. Velg maks 3 saker i `Prioritert` som faktisk skal styres neste uke.
3. Be teamet demonstrere alt som staar i `Klar for test`.
4. Flytt kun saker til `Ferdig` etter demo eller faktisk verifikasjon.

---

## Eksempel pa hvordan et kort skal se ut

### Sak: Generere daglig produksjonsrapport per dato

**Type:** Story  
**Epic:** Produksjonsrapporter  
**Prioritet:** Hoy  
**Status:** Prioritert

**Bakgrunn:**
Bakeriet trenger en samlet oversikt over hva som skal produseres per leveringsdato.

**Mal:**
Redusere manuell telling og sikre at produksjonen starter med korrekt grunnlag hver dag.

**Leveranse:**
Opprette logikk og API-visning for produksjonsrapport som summerer produkter, antall ordre og antall kunder per dato.

**Akseptansekriterier:**
- Rapport kan hentes for valgt dato.
- Rapport summerer alle ordrelinjer korrekt.
- Rapport viser totaler per produkt.
- Rapport kan brukes av admin uten manuell etterbehandling.

**Test:**
Verifisere mot et kjent datasett og sammenligne med ordrene for samme dato.

**Statusnotat til ledelsen:**
Saken gir bakeriet daglig produksjonsgrunnlag og bor prioriteres tidlig fordi den gir direkte operativ verdi.

---

## Styringsvisning for ledere

Ledere trenger vanligvis ikke alle tekniske detaljer. Bruk disse visningene:

### 1. Lederoversikt
Vis kun kolonnene `Prioritert`, `Satt i gang`, `Blokkert`, `Test` og `Ferdig`.

### 2. Risikoview
Filtrer pa:
- `Blokkert`
- `Hoy`
- saker med forfallsdato innen 7 dager

### 3. Leveranseview
Grupper pa epic for a se hvilke forretningsomrader som faktisk beveger seg.

### 4. Ukesrapport
Rapporter hver uke:
- antall saker flyttet til `Ferdig`
- antall saker som er `Blokkert`
- topp 3 neste prioriteringer
- eventuelle beslutninger som kreves fra ledelsen

---

## Praktisk oppsett i Trello

Bruk disse listene:

1. Ide
2. Avklart
3. Prioritert
4. Satt i gang
5. Blokkert
6. Klar for test
7. Test
8. Ferdig
9. Arkiv

Anbefalt bruk i Trello:

- ett kort per sak
- labels for fagomrade og prioritet
- custom fields for ansvarlig, frist og estimat
- checklist for akseptansekriterier
- fast ukentlig arkivering av eldre ferdige kort

---

## Praktisk oppsett i Jira

Anbefalt workflow:

`Ide -> Avklart -> Prioritert -> Satt i gang -> Blokkert -> Satt i gang -> Klar for test -> Test -> Ferdig -> Arkiv`

Anbefalte felter i Jira:

- Summary
- Description
- Issue Type
- Epic Link
- Priority
- Assignee
- Due Date
- Labels
- Story Points eller estimat
- Acceptance Criteria
- Test Notes
- Leadership Status Note

Anbefalte dashboards:

- saker per status
- saker per epic
- blokkere per ansvarlig
- fullforte saker siste 30 dager
- hoy prioritet som ikke er startet

---

## Moteformat for ledelsesoppfolging

Bruk tavlen i et fast ukentlig mote med denne agendaen:

1. Hva ble ferdig siden sist?
2. Hva er satt i gang na?
3. Hvilke saker er blokkert?
4. Hva ma ledelsen beslutte?
5. Hva er topp prioritet neste uke?

Dette holder fokus pa progresjon, risiko og beslutningsbehov.

---

## Minimumskrav for god tavlehygiene

- Ingen saker skal ligge i `Satt i gang` uten ansvarlig.
- Ingen saker skal ligge i `Blokkert` uten forklaring.
- Ingen saker skal flyttes til `Ferdig` uten test eller eksplisitt godkjenning.
- Alle hoyprioritetssaker skal ha frist.
- Alle saker i `Prioritert` skal ha en kort forretningsforklaring.

---

## Anbefalt start

Hvis dere vil komme raskt i gang, bruk denne oppstarten:

1. Opprett tavlen med kolonnene over.
2. Opprett epicene i dette dokumentet.
3. Legg inn backlog-tabellen som de 10-15 forste sakene.
4. Legg til labels og prioritetsskala.
5. Avtal ett fast ledermote der tavlen brukes som styringsflate.

Da far ledelsen en enkel og troverdig oversikt over hva som vurderes, hva som er i arbeid, og hva som faktisk er levert.
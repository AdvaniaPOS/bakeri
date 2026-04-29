# PanisOS — Master Prompt (Enterprise Bakery SaaS)

> **Bruk:** Lim hele dette dokumentet inn som system-/context-prompt i Cursor, Copilot Chat, Claude eller annen LLM før du genererer kode. Det dekker arkitektur, datamodell, B2B-/B2C-flyter, Nets Easy, Susoft-integrasjon, UI (Shopify-style) og infrastruktur.

---

## 0. Rolle og leveransekrav til LLM

Du er **Senior Full-Stack Architect** for et multi-tenant SaaS for bakerier kalt **PanisOS**. Du skal:

- Skrive **produksjonsklar kode** (ikke pseudokode), med typing, validering, feilhåndtering og tester.
- Følge **Clean Architecture** + **Dependency Injection**.
- Aldri bryte **multi-tenant isolasjon** (`tenant_id` skal være med i hvert query, og håndheves av Postgres RLS).
- Aldri lekke hemmeligheter; alle nøkler leses fra `process.env` / `.env`.
- Bruke `date-fns-tz` låst til `Europe/Oslo` for ALLE datoberegninger.
- Skrive **defensive tester** for cut-off-logikken (spesielt helge- og helligdags-overganger).
- Foretrekke **effektive SQL-queries** (én query med joins/aggregater) fremfor tunge looper i Node.
- Levere kode i små, kjørbare PR-vennlige biter med tydelige filstier.

Hvis noe er tvetydig: still ETT presist spørsmål før du genererer. Ellers: lever koden.

---

## 1. Forretningskontekst

**PanisOS** erstatter fragmenterte manuelle prosesser i bakerier (lapper, Excel, telefonbeskjeder) med én sentral kilde for sannhet. Første kunde er **Lampeland Bakeri**, men systemet er designet som **multi-tenant SaaS** for å skalere til flere bakerikjeder.

**Tre hovedflyter:**

1. **B2B Standing Orders** — Faste ukentlige leveranser til butikker, kafeer, kantiner. Mandag–søndag matrise per kunde/produkt, med avvikshåndtering (overrides) for spesifikke datoer.
2. **B2C Onetime Orders** — Privatkunder bestiller kaker (med tekst/bilde) eller brød via headless storefront. Streng cut-off-logikk og Nets Easy reserve-and-capture.
3. **Internt utsalg** — Bakeriets egne utsalgssteder (Lampeland, Lyngdal, …) henter fra samme produksjonspott.

Alle tre flyter ender opp i **én aggregert produksjonsliste** for bakeren.

---

## 2. Tech Stack (lås disse valgene)

| Lag | Teknologi |
|---|---|
| Backend API | **Node.js 20 LTS + NestJS 10** |
| ORM | **Prisma 5** |
| Database | **PostgreSQL 16** (med Row-Level Security) |
| Async/Queue | **BullMQ + Redis 7** |
| Frontend | **React 18 + Vite + TypeScript** |
| UI | **Tailwind CSS + Shadcn/UI** (Shopify-inspirert) |
| Auth | **JWT (access + refresh)** + Cloudflare Access (Zero Trust) for admin |
| Payment | **Nets Easy (Nexi) — Reserve & Capture** |
| ERP-sync | **Susoft REST API** (eksisterer) |
| Validering | **Zod** (frontend + DTO på backend) |
| Tester | **Vitest** (unit) + **Playwright** (E2E) |
| Tid/sone | **date-fns + date-fns-tz**, låst til `Europe/Oslo` |
| Hosting | **Linux (Ubuntu 22.04)** bak **Cloudflare Tunnel** |
| Containerisering | **docker-compose** (api, worker, postgres, redis, cloudflared) |

---

## 3. Multi-tenancy & sikkerhet

- Hver tenant (bakerikjede) har en egen `tenants` rad. ALLE forretningstabeller har `tenant_id UUID NOT NULL`.
- **Postgres RLS** aktiveres på alle tenant-tabeller. Policy: `USING (tenant_id = current_setting('app.tenant_id')::uuid)`.
- NestJS middleware setter `SET LOCAL app.tenant_id = '<uuid>'` på connection per request, basert på JWT-claim.
- **Roller (RBAC):** `SUPERADMIN`, `ADMIN`, `BAKER`, `PACKER`, `STORE_MANAGER`, `CUSTOMER` (B2C).
- SUPERADMIN er eneste rolle som kan krysse tenants (uten RLS — bruker en egen DB-rolle).
- Cloudflare Access foran `/admin` og `/superadmin` ruter. B2C-storefront er offentlig.
- Rate-limit alle offentlige endepunkter (`@nestjs/throttler`).
- Aldri logg PII / kortdata. Maskér e-post i logger.

---

## 4. Datamodell (Prisma)

```prisma
// schema.prisma — kjerneutdrag, utvid etter behov

model Tenant {
  id           String   @id @default(uuid())
  name         String
  slug         String   @unique
  susoftConfig Json?    // { baseUrl, clientId, clientSecret (encrypted) }
  createdAt    DateTime @default(now())

  users        User[]
  customers    Customer[]
  products     Product[]
}

model User {
  id            String   @id @default(uuid())
  tenantId      String
  email         String
  passwordHash  String
  role          Role
  isActive      Boolean  @default(true)
  tenant        Tenant   @relation(fields: [tenantId], references: [id])

  @@unique([tenantId, email])
}

enum Role { SUPERADMIN ADMIN BAKER PACKER STORE_MANAGER CUSTOMER }

model Product {
  id           String   @id @default(uuid())
  tenantId     String
  susoftId     String?  // mapping mot Susoft varenr
  sku          String?
  name         String
  category     String   // "Brød", "Kaker", "Kremkaker", ...
  unitWeightKg Decimal  // kritisk for deig-beregning
  isActive     Boolean  @default(true)
  priceB2C     Decimal? // pris i nettbutikk (inkl. mva)
  vatRate      Decimal  @default(15) // matvare
  metadata     Json?    // bilde, allergener, ingredienser

  tenant       Tenant   @relation(fields: [tenantId], references: [id])
  standingOrders StandingOrder[]
  overrides      OrderOverride[]

  @@unique([tenantId, susoftId])
  @@unique([tenantId, sku])
  @@index([tenantId, isActive])
}

model Customer {
  id              String   @id @default(uuid())
  tenantId        String
  susoftCustomerId String?
  name            String
  email           String?
  phone           String?
  routeId         String?  // leveranserute
  pausedFrom      DateTime?
  pausedTo        DateTime?
  isActive        Boolean  @default(true)

  tenant          Tenant   @relation(fields: [tenantId], references: [id])
  standingOrders  StandingOrder[]
  overrides       OrderOverride[]
  orders          Order[]

  @@unique([tenantId, susoftCustomerId])
  @@index([tenantId, routeId])
}

model Route {
  id        String  @id @default(uuid())
  tenantId  String
  name      String  // "Rollag", "Kongsberg", "Drammen"
  driver    String?
  sortOrder Int     @default(0)
}

// ===== STANDING ORDER (B2B mal) =====
model StandingOrder {
  id         String  @id @default(uuid())
  tenantId   String
  customerId String
  productId  String
  dayOfWeek  Int     // 0=søndag .. 6=lørdag (date-fns konvensjon)
  quantity   Decimal
  isActive   Boolean @default(true)
  isFavorite Boolean @default(false) // ⭐ vises øverst ved override

  customer Customer @relation(fields: [customerId], references: [id])
  product  Product  @relation(fields: [productId], references: [id])

  @@unique([customerId, productId, dayOfWeek])
  @@index([tenantId, dayOfWeek])
}

// ===== ORDER OVERRIDE (B2B avvik) =====
model OrderOverride {
  id              String       @id @default(uuid())
  tenantId        String
  customerId      String
  productId       String
  targetDate      DateTime     @db.Date  // kun dato, ingen tid
  type            OverrideType
  newQuantity     Decimal?     // for REPLACE
  adjustmentValue Decimal?     // for ADJUST (+/-)
  reason          String?
  metadata        Json?        // kake-tekst, bilde-URL, allergi-notat
  createdBy       String
  createdAt       DateTime     @default(now())

  customer Customer @relation(fields: [customerId], references: [id])
  product  Product  @relation(fields: [productId], references: [id])

  @@unique([customerId, productId, targetDate])
  @@index([tenantId, targetDate])
}

enum OverrideType { REPLACE ADJUST CANCEL ADD }

// ===== ORDERS (B2C + ad-hoc B2B + interne utsalg) =====
model Order {
  id             String      @id @default(uuid())
  tenantId       String
  orderNumber    Int         // sekvens per tenant
  channel        OrderChannel
  customerId     String?     // null for anonym B2C (gjest)
  guestEmail     String?
  guestPhone     String?
  guestName      String?
  pickupLocation String?     // "Lampeland", "Lyngdal", eller "DELIVERY"
  routeId        String?
  deliveryDate   DateTime    @db.Date
  deliverySlot   String?     // "08:00-10:00"
  status         OrderStatus @default(PENDING)
  paymentStatus  PaymentStatus @default(PENDING)
  paymentId      String?     // Nets Easy paymentId (pay-...)
  totalAmount    Decimal
  totalVat       Decimal
  notes          String?
  createdAt      DateTime    @default(now())
  updatedAt      DateTime    @updatedAt

  customer Customer? @relation(fields: [customerId], references: [id])
  lines    OrderLine[]
  events   OrderEvent[]

  @@unique([tenantId, orderNumber])
  @@index([tenantId, deliveryDate, status])
  @@index([tenantId, paymentStatus])
}

model OrderLine {
  id              String  @id @default(uuid())
  orderId         String
  productId       String
  quantity        Decimal
  unitPrice       Decimal
  vatRate         Decimal
  lineTotal       Decimal
  specialInstructions Json? // {text:"Gratulerer Ole 5 år", imageUrl:"...", allergies:["nøtter"]}

  order   Order   @relation(fields: [orderId], references: [id], onDelete: Cascade)
  product Product @relation(fields: [productId], references: [id])
}

model OrderEvent {
  id        String   @id @default(uuid())
  orderId   String
  type      String   // "CREATED", "PAYMENT_RESERVED", "PAYMENT_CAPTURED", "STATUS_CHANGED", ...
  payload   Json
  actorId   String?
  createdAt DateTime @default(now())

  order Order @relation(fields: [orderId], references: [id], onDelete: Cascade)
}

enum OrderChannel { B2B_STANDING B2B_OVERRIDE B2B_ADHOC B2C_ONLINE INTERNAL_OUTLET }
enum OrderStatus  { PENDING CONFIRMED IN_PRODUCTION READY_FOR_PICKUP OUT_FOR_DELIVERY DELIVERED CANCELLED }
enum PaymentStatus { PENDING RESERVED CAPTURED PARTIALLY_REFUNDED REFUNDED FAILED CANCELLED }

// ===== Susoft outbox / sync log =====
model SyncLog {
  id         String   @id @default(uuid())
  tenantId   String
  entityType String   // "ORDER", "PRODUCT", "CUSTOMER"
  entityId   String
  direction  String   // "PUSH" | "PULL"
  status     String   // "PENDING", "SUCCESS", "FAILED", "RETRYING"
  attempts   Int      @default(0)
  lastError  String?
  payload    Json?
  response   Json?
  createdAt  DateTime @default(now())
  updatedAt  DateTime @updatedAt

  @@index([tenantId, status, entityType])
}

model HolidayCalendar {
  id        String   @id @default(uuid())
  tenantId  String?  // null = global (norske helligdager)
  date      DateTime @db.Date
  name      String
  isClosed  Boolean  @default(true)

  @@unique([tenantId, date])
}
```

---

## 5. Cut-off & Scheduling-motor (B2C)

**Forretningsregler (Norge, Europe/Oslo):**

- Daglig cut-off **kl. 10:00**: bestillinger før 10:00 kan leveres **neste virkedag**.
- Bestilling **etter 10:00 fredag**, eller når som helst **lørdag/søndag** ⇒ tidligste leveringsdag = **tirsdag**.
- Helligdager (norske + tenant-spesifikke "stengt"-dager) hoppes over.
- Spesialkaker (med navn/bilde): minimum **3 virkedager** varsel — konfigurerbart per produkt (`metadata.minLeadDays`).

```ts
// scheduling.service.ts
import { addDays, getDay, isBefore, set, startOfDay } from 'date-fns';
import { utcToZonedTime, zonedTimeToUtc } from 'date-fns-tz';

const TZ = 'Europe/Oslo';

export class SchedulingService {
  constructor(private holidays: HolidayService) {}

  /** Tidligste lovlige leveringsdato for B2C-bestilling lagt inn `now`. */
  async earliestDeliveryDate(tenantId: string, now: Date, minLeadDays = 1): Promise<Date> {
    const local = utcToZonedTime(now, TZ);
    const cutoff = set(local, { hours: 10, minutes: 0, seconds: 0, milliseconds: 0 });

    // Start: i morgen hvis før 10:00, ellers overimorgen
    let candidate = startOfDay(addDays(local, isBefore(local, cutoff) ? 1 : 2));

    // Min lead days (spesialprodukter)
    const minDate = startOfDay(addDays(local, minLeadDays));
    if (isBefore(candidate, minDate)) candidate = minDate;

    // Hopp over helg + helligdag
    while (await this.isClosed(tenantId, candidate)) {
      candidate = addDays(candidate, 1);
    }
    return zonedTimeToUtc(candidate, TZ);
  }

  private async isClosed(tenantId: string, day: Date): Promise<boolean> {
    const dow = getDay(day); // 0=søn, 6=lør
    if (dow === 0 || dow === 6) return true; // bakeriet stengt helg (konfigurerbart)
    return this.holidays.isHoliday(tenantId, day);
  }
}
```

**Tester (defensive):**

- Bestilling torsdag 09:59 ⇒ levering fredag.
- Bestilling torsdag 10:01 ⇒ levering mandag (hopper helg).
- Bestilling fredag 09:59 ⇒ levering lørdag → må hoppe ⇒ mandag.
- Bestilling fredag 10:01 ⇒ tirsdag.
- Bestilling lørdag 14:00 ⇒ tirsdag.
- Bestilling søndag 23:59 ⇒ tirsdag.
- 17. mai på en onsdag ⇒ hoppes over.
- DST-overgang vår/høst ⇒ ingen feil i datoaritmetikk.

---

## 6. Produksjons-aggregator (Master Aggregator)

**Mål:** For en gitt `targetDate`, returner:

1. **BakerSheet** — flat liste `{product, totalQty, totalWeightKg}` (kun produktet og totalt antall).
2. **AdminSheet** — detaljert per kunde/rute/B2C-ordre.

**Algoritme (single-pass, SQL-tungt):**

```ts
// production.service.ts
async generateProductionSheet(tenantId: string, targetDate: Date) {
  const day = startOfDayOslo(targetDate);
  const dow = getDay(day);

  // 3 parallelle queries
  const [standing, overrides, b2cLines] = await Promise.all([
    this.prisma.standingOrder.findMany({
      where: { tenantId, isActive: true, dayOfWeek: dow,
               customer: { isActive: true,
                           OR: [{ pausedFrom: null }, { pausedTo: { lt: day } }, { pausedFrom: { gt: day } }] } },
      include: { product: true, customer: true },
    }),
    this.prisma.orderOverride.findMany({
      where: { tenantId, targetDate: day },
      include: { product: true, customer: true },
    }),
    this.prisma.orderLine.findMany({
      where: { order: { tenantId, deliveryDate: day,
                        status: { notIn: ['CANCELLED'] },
                        channel: { in: ['B2C_ONLINE','INTERNAL_OUTLET','B2B_ADHOC'] } } },
      include: { product: true, order: { include: { customer: true } } },
    }),
  ]);

  const map = new Map<string, AggregatedLine>();

  // 1) Standing orders (med override-flette per (kunde,produkt))
  for (const so of standing) {
    const ov = overrides.find(o => o.customerId === so.customerId && o.productId === so.productId);
    let qty = Number(so.quantity);
    if (ov) {
      if (ov.type === 'REPLACE') qty = Number(ov.newQuantity);
      else if (ov.type === 'ADJUST') qty += Number(ov.adjustmentValue);
      else if (ov.type === 'CANCEL') qty = 0;
    }
    if (qty > 0) addToMap(map, so.product, qty, { customer: so.customer, source: 'STANDING' });
  }

  // 2) ADD-overrides (varer kunden vanligvis ikke har)
  for (const ov of overrides) {
    if (ov.type !== 'ADD') continue;
    const qty = Number(ov.newQuantity ?? 0);
    if (qty > 0) addToMap(map, ov.product, qty, { customer: ov.customer, source: 'OVERRIDE_ADD' });
  }

  // 3) B2C + ad-hoc + internt utsalg
  for (const line of b2cLines) {
    addToMap(map, line.product, Number(line.quantity),
             { order: line.order, source: line.order.channel });
  }

  return {
    bakerSheet: [...map.values()].map(toBakerRow),    // {productName, totalQty, totalWeightKg}
    adminSheet: [...map.values()].map(toAdminRow),    // detaljert breakdown
  };
}
```

**Krav:** Single-call, < 200 ms for 500 kunder × 100 produkter. Bruk `@@index` aggressivt.

---

## 7. B2B-rutiner (Standing Orders)

### 7.1 Opprette/redigere mal
- UI: matrise (rader = produkter, kolonner = man–søn). Inline edit, autosave (debounce 800 ms).
- ⭐ Favoritt-toggle per linje for raskere override-flow.
- Bulk-import: CSV-opplasting per kunde.

### 7.2 Avvik via telefon
1. Admin søker kunde (`Cmd+K` global søk).
2. Velger "Endre neste levering" → datovelger (default = neste leveringsdag).
3. Ser malen for valgt dato med eksisterende overrides anvendt; kan øke/redusere/kansellere/legge til linje.
4. Lagring → `OrderOverride` upsert (unique på `customer+product+date`).

### 7.3 Ferie/pause
- `Customer.pausedFrom` / `pausedTo`. Aggregatoren hopper over disse.

### 7.4 Helligdager
- `HolidayCalendar` (global + tenant). Admin får varsel: "Mandag er 2. pinsedag — kanseller alle eller flytt til tirsdag?"

---

## 8. B2C Storefront

### 8.1 API (headless)
- `POST /api/v1/storefront/products` — katalog (kun `isActive` + `priceB2C != null`).
- `POST /api/v1/storefront/availability` — body: `{productIds:[...]}` → `{earliestDate, blockedDates:[...]}`.
- `POST /api/v1/storefront/orders` — opprett ordre, returner `{orderId, paymentRedirectUrl}`.
- `POST /api/v1/storefront/upload` — bilde-vedlegg for kake (S3/R2, signert URL).

### 8.2 Validering (Zod)
```ts
const B2COrderDto = z.object({
  tenantSlug: z.string(),
  pickupLocation: z.enum(['Lampeland','Lyngdal','DELIVERY']),
  deliveryDate: z.coerce.date(),
  guest: z.object({ name: z.string().min(2), email: z.string().email(), phone: z.string().min(8) }),
  lines: z.array(z.object({
    productId: z.string().uuid(),
    quantity: z.number().int().positive().max(50),
    specialInstructions: z.object({
      text: z.string().max(120).optional(),
      imageUrl: z.string().url().optional(),
      allergies: z.array(z.string()).optional(),
    }).optional(),
  })).min(1),
});
```

### 8.3 Server-side validering
- Backend RE-VALIDERER `earliestDeliveryDate` mot scheduling-service. Aldri stol på frontend-dato.
- Sjekk produktets `metadata.minLeadDays`.

---

## 9. Nets Easy — Reserve & Capture

### 9.1 Juridisk
- **Standardvarer:** Capture FØRST når varen er klar/levert.
- **Tilvirkningskjøp** (spesialkake med tekst/bilde): juridisk lov å capture tidligere — men best praksis er fortsatt capture på produksjonsdagen.
- Korthold-reservasjon: ~7 dager. For bestillinger > 7 dager fram: enten capture umiddelbart (tilvirkning) eller trigge re-authorization.

### 9.2 Flyt
1. **Checkout:** `POST /v1/payments` med `charge: false`, `myReference: orderNumber`, `webhooks: [{eventName:"payment.checkout.completed", url: ...}, ...]` → lagre `paymentId`, set `paymentStatus = PENDING`.
2. **Webhook `payment.checkout.completed`:** sett `paymentStatus = RESERVED`, `status = CONFIRMED`.
3. **Status → READY_FOR_PICKUP / DELIVERED:** call `POST /v1/payments/{id}/charges` med beløp → `CAPTURED`.
4. **Cancel før capture:** `POST /v1/payments/{id}/cancels` → `CANCELLED`.
5. **Refund etter capture:** `POST /v1/payments/{id}/refunds` → `PARTIALLY_REFUNDED` / `REFUNDED`.

### 9.3 PaymentService kontrakt
```ts
interface PaymentService {
  createReservation(order: Order): Promise<{ paymentId: string; redirectUrl: string }>;
  capture(orderId: string, amount?: Decimal): Promise<void>;     // amount = full hvis utelatt
  cancel(orderId: string): Promise<void>;
  refund(orderId: string, amount: Decimal, reason: string): Promise<void>;
  handleWebhook(signature: string, body: unknown): Promise<void>;
}
```

### 9.4 Sikkerhetsregler
- Capture nektes hvis `paymentStatus !== RESERVED`.
- Capture nektes hvis `status === CANCELLED`.
- Webhook signatur (HMAC) MÅ verifiseres før handling.
- Idempotens: bruk `Idempotency-Key` header på alle write-kall mot Nets.
- Logg hver state-transition i `OrderEvent`.

---

## 10. Susoft-integrasjon (Outbox-mønster)

### 10.1 Eksisterende Susoft-API (se `susoft api.txt`)
- Auth: OAuth2 client_credentials.
- Endepunkter brukt: `/product/search?activityFlag=ALL`, `/product/category/tree`, `/customer/search`, `/order` (POST).

### 10.2 Push-flyt (PanisOS → Susoft)
- Trigger: `OrderStatus → DELIVERED`.
- Worker (BullMQ queue `susoft-push`):
  1. Hent `Order` + `lines` + `customer` (med `susoftCustomerId`).
  2. Map til Susoft-format.
  3. POST `/order`. Lagre response i `SyncLog`.
  4. Feil ⇒ exponential backoff (1m, 5m, 15m, 1h, 6h, 24h), max 6 forsøk.
  5. Etter siste forsøk: `status = FAILED`, varsle admin (in-app + e-post).

### 10.3 Pull-flyt (Susoft → PanisOS)
- Allerede implementert i `app/services/susoft.py` (Python prototype). I prod: re-implementer i NestJS worker `susoft-pull` (cron hver 15 min) for produkter, kunder, kategorier.
- Inkrementell sync via `modifiedSince` parameter.
- Kategori-tree caches 1 time i Redis.

---

## 11. UI — Shopify-inspirert Admin

### 11.1 Layout
- Venstre sidebar (kollapsbar): Dashbord, Ordrer, Produkter, Kunder, Ruter, Betalinger, Susoft-sync, Innstillinger.
- Topbar: tenant-velger (for SUPERADMIN), global søk (`Cmd+K`), notifikasjoner, bruker-meny.

### 11.2 Ordrer-side (hovedbilde)
- 4 helse-kort øverst: "Dagens produksjonsbehov (1350 varer)", "Ubehandlede B2C (12)", "Reservert hos Nets (8 450 kr)", "Venter Susoft-sync (4)".
- Tabs: **Alle** | **I dag** | **B2B** | **B2C** | **Ubetalt** | **Avvik**.
- Søkefelt + filter-chips (status, rute, kunde, dato-range).
- DataTable (Shadcn) med kolonner: ☐ | Ordre# | Dato/Tid | Kunde | Type-badge | Rute/Hentested | Total | Status-badge | Betalingsstatus-badge | "..." (kontekstmeny).
- **Bulk actions** (vises når 1+ rad valgt): Capture Payment, Send to Susoft, Mark Delivered, Print pakkliste, Eksporter CSV.

### 11.3 Status-badges (farge)
| Status | Farge |
|---|---|
| PENDING | grå |
| CONFIRMED | blå |
| IN_PRODUCTION | oransje |
| READY_FOR_PICKUP | lilla |
| OUT_FOR_DELIVERY | cyan |
| DELIVERED | grønn |
| CANCELLED | rød |
| RESERVED | gul |
| CAPTURED | grønn |
| FAILED | rød |
| Sync Pending | grå (pulserende) |
| Synced (Susoft) | grønn med checkmark |

### 11.4 Standing Order-editor (kunde-detalj)
- Tab `Fastbestilling` på kundekortet.
- Matrise: produkter (rader, søkbar) × ukedager (kolonner). Tom celle = `–` (ingen levering).
- Inline number input, debounce-autosave 800 ms, optimistisk UI.
- ⭐ favoritt-toggle.
- Knapper: "Lagre mal", "Sett på pause" (datepicker-range), "Kopier fra annen kunde", "Eksporter".

### 11.5 Bakeri-terminal (Flour-proof)
- Stort fonts, høy kontrast, touch-vennlig.
- Side 1: Dagens BakerSheet (produkt, antall, total deig kg). Group by kategori.
- Side 2: Pakkerekkefølge per rute.
- Knapp per rute: "Pakket ✓" → setter linjer til `READY_FOR_PICKUP` / `OUT_FOR_DELIVERY`.

### 11.6 B2C Storefront
- Egen Vite-app (eller Next.js) på eget subdomene.
- Min-versjon: katalog → kakekonfigurator (tekst, bilde-upload, allergier) → kalender (kun lovlige datoer fra `availability`-API) → checkout (Nets Easy embedded).
- Bestillingsbekreftelse på e-post.

---

## 12. Infrastruktur

### 12.1 docker-compose.yml (prod)
```yaml
services:
  api:
    build: ./api
    env_file: .env
    depends_on: [postgres, redis]
    restart: unless-stopped
  worker:
    build: ./api
    command: node dist/worker.js
    env_file: .env
    depends_on: [postgres, redis]
    restart: unless-stopped
  postgres:
    image: postgres:16-alpine
    volumes: ["pgdata:/var/lib/postgresql/data"]
    environment: { POSTGRES_PASSWORD: ${PG_PASSWORD} }
    restart: unless-stopped
  redis:
    image: redis:7-alpine
    restart: unless-stopped
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --no-autoupdate run --token ${CF_TUNNEL_TOKEN}
    restart: unless-stopped
volumes: { pgdata: }
```

### 12.2 RLS-migrasjon (eksempel)
```sql
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON customers
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- Repeat for products, orders, order_lines, standing_orders, order_overrides, ...
```

### 12.3 Observability
- Pino logger (JSON), shipped til Loki/Grafana eller Better Stack.
- OpenTelemetry tracing for API + workers.
- Healthchecks: `/healthz` (liveness), `/readyz` (DB+Redis+Susoft ping).

---

## 13. Tester (krav)

| Område | Type | Eksempel |
|---|---|---|
| Cut-off | Unit | Tabelldrevet test for alle ukedager/tider × helligdager |
| Aggregator | Unit + integration | Standing + override + B2C på samme dato gir korrekt total |
| RLS | Integration | Tenant A kan ikke lese tenant B's data, selv ved query-injection |
| Nets Capture-guard | Unit | Capture på CANCELLED/FAILED ordre kaster feil |
| Susoft retry | Integration | 5xx → backoff til SUCCESS / FAILED etter max attempts |
| B2C E2E | Playwright | Bestill kake → betal (Nets test) → admin captures → ordre DELIVERED |
| Standing matrix UI | E2E | Endre 1 celle → autosave → reload → verdi persistert |

---

## 14. Leveranse-rekkefølge (anbefalt sprint-rekkefølge)

1. **Sprint 0:** Repo-scaffold (NestJS + Prisma + Vite), docker-compose, CI (GitHub Actions), RLS-baseline.
2. **Sprint 1:** Auth (JWT + roller), Tenants, Users, SuperAdmin-portal.
3. **Sprint 2:** Produkter + Kunder CRUD + Susoft pull-sync.
4. **Sprint 3:** Standing Orders matrix UI + Overrides + Helligdager.
5. **Sprint 4:** Production aggregator + Bakeri-terminal.
6. **Sprint 5:** B2C storefront + Scheduling + Nets Easy reserve & capture.
7. **Sprint 6:** Susoft push-outbox + bulk actions i admin.
8. **Sprint 7:** Rapporter, eksport, varsler, polering.

---

## 15. Spesifikke TASK-blokker (lim inn én av gangen til Copilot)

### TASK A — Prisma schema + RLS-migrasjon
> Generer fullstendig `schema.prisma` basert på seksjon 4. Lag Prisma-migrasjon som inkluderer rå-SQL for å aktivere RLS på alle tenant-tabeller. Skriv NestJS `PrismaService` som setter `app.tenant_id` per request via en `TenantContextMiddleware` som leser JWT.

### TASK B — Scheduling
> Implementer `SchedulingService` (seksjon 5) i NestJS. Inkluder `HolidayService` med seed for norske helligdager 2026–2030. Skriv Vitest-tester for ALLE casene listet i seksjon 5 + DST-overgang.

### TASK C — Production Aggregator
> Implementer `ProductionService.generateProductionSheet` (seksjon 6). Lever én optimalisert SQL-vei (rå Prisma queries med `include`). Mål: < 200 ms for 500 kunder × 100 produkter på lokal Postgres. Skriv integration-test med seed-data.

### TASK D — Standing Orders matrix (frontend)
> React + Shadcn DataTable-style komponent for matrise (produkt × ukedag) med inline number input, debounced autosave (800 ms), optimistisk UI, ⭐ favoritt-toggle, og "Sett på pause"-modal med date-range picker.

### TASK E — B2C Checkout + Nets Easy
> Implementer `PaymentService` (seksjon 9.3), Nets Easy-klient med Idempotency-Key og HMAC-webhook-validering. B2C `/storefront/orders` POST-endepunkt: validerer dato server-side via SchedulingService, oppretter Order + lines + Nets reservation, returnerer `redirectUrl`. Webhook-handler oppdaterer `paymentStatus`. Skriv tester for capture-guards (seksjon 9.4).

### TASK F — Susoft outbox-worker
> BullMQ queue `susoft-push`, worker som lytter på `OrderStatus → DELIVERED`, mapper til Susoft-format, POST til `/order`, logger i `SyncLog`, exponential backoff (1m/5m/15m/1h/6h/24h, max 6). In-app notifikasjon ved endelig FAILED.

### TASK G — Admin orders-side
> Bygg Shopify-inspirert ordrer-side (seksjon 11.2) med 4 helse-kort, tabs, søk, filter-chips, DataTable med fargekodede badges, bulk actions (Capture, Send to Susoft, Mark Delivered). Bruk Tailwind + Shadcn.

---

## 16. Hva LLM IKKE skal gjøre

- Ikke generer Excel- eller papir-baserte workarounds.
- Ikke gjør client-side dato-/cut-off-validering til "sannhet" — server REVALIDERER alltid.
- Ikke commit secrets, ikke logg kortdata eller Nets payment payloads i klartekst.
- Ikke bypass RLS med `prisma.$queryRawUnsafe` uten eksplisitt SUPERADMIN-kontekst.
- Ikke generer ordrer "5 uker fram i tid" — aggregatoren regner just-in-time.
- Ikke bruk `new Date()` direkte for forretningslogikk — alltid via `now()`-helper som kan mockes i tester.

---

## 17. Konvensjoner

- Filnavn: `kebab-case.ts` for filer, `PascalCase` for klasser, `camelCase` for variabler.
- API-versjonering: `/api/v1/...`.
- Alle DTO valideres med Zod (`createZodDto` for NestJS).
- Pengebeløp: `Decimal` (Prisma) — aldri `number` for pris/total.
- Tid lagres som UTC i DB; konverteres til `Europe/Oslo` ved presentasjon.
- Migrations: `prisma migrate dev` lokalt, `prisma migrate deploy` i CI/CD.

---

**SLUTT PÅ MASTER PROMPT.** Bekreft at du har lest hele dette dokumentet før du genererer kode, og spør hvilken TASK (A–G) brukeren vil starte på.

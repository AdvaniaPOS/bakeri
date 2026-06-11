"""
SuSoft -> Lampeland-bakeri ordre-INGESTION (polling).

Henter ordre fra SuSoft `GET /order/list` hver 5. minutt og dedupliserer
mot `orders.susoft_uuid`. Ordrer som ikke finnes lokalt opprettes; ordrer
som allerede finnes (samme uuid + samme tenant) hoppes over.

Designvalg (bekreftet med bruker):
- Manglende `customer` -> bruk/opprett tenant-spesifikk "Ukjent kunde"
- `type == "CART"` -> opprett som DRAFT-status
- Alle shopId-er ingestes (ingen filter)
- Kjøres hvert 5. minutt

NB: SuSoft `/order/list` filtrerer på `orderDate`, ikke pickup/delivery,
så vi pull-er et bredt vindu (siste 30 dager). Klient-side beholder vi
alle rader uavhengig av pickup/delivery-tid.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid as uuid_module
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    Customer,
    Order,
    OrderLine,
    OrderStatus,
    Product,
    SyncStatus,
)
from .susoft import (
    SuSoftAPIError,
    SuSoftService,
    parse_susoft_datetime,
    pick_susoft_fulfillment,
)

logger = logging.getLogger(__name__)

UKJENT_KUNDE_SUSOFT_ID = "__ukjent__"
DEFAULT_POLL_DAYS_BACK = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_unknown_customer(db: Session, tenant_id: int) -> Customer:
    """Henter (eller oppretter) tenant-spesifikk 'Ukjent kunde'."""
    customer = db.execute(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.susoft_customer_id == UKJENT_KUNDE_SUSOFT_ID,
        )
    ).scalar_one_or_none()
    if customer:
        return customer

    customer = Customer(
        tenant_id=tenant_id,
        susoft_customer_id=UKJENT_KUNDE_SUSOFT_ID,
        name="Ukjent kunde (SuSoft)",
        company_name=None,
        country="Norway",
        is_active=True,
        order_lead_days=14,
    )
    db.add(customer)
    db.flush()
    logger.info("Opprettet 'Ukjent kunde' for tenant %s (id=%s)", tenant_id, customer.id)
    return customer


def _extract_local_order_refs_from_alt_id(
    alt_id_raw: Any,
    tenant_id: int,
) -> Tuple[Optional[uuid_module.UUID], Optional[int]]:
    """
    Parse alternativeId fra SuSoft til lokal ordreidentitet.

    St\u00f8tter nytt UUID-format `t<tenant>-ou<uuidhex>` og forrige tenant-
    prefikset format `t<tenant>-o<id>`. Nakne integer-verdier matches ikke
    lenger siden de kan kollidere etter DB-reset/kloning.
    """
    if alt_id_raw in (None, ""):
        return None, None

    alt_id = str(alt_id_raw).strip()
    prefix = f"t{tenant_id}-"
    if not alt_id.startswith(prefix):
        return None, None

    local_token = alt_id[len(prefix):]
    if local_token.startswith("ou"):
        uuid_token = local_token[2:].strip()
        if not uuid_token:
            return None, None
        try:
            return uuid_module.UUID(uuid_token), None
        except (TypeError, ValueError):
            return None, None

    if local_token.startswith("o"):
        try:
            return None, int(local_token[1:])
        except (TypeError, ValueError):
            return None, None

    return None, None


def _find_or_create_customer_from_payload(
    db: Session, tenant_id: int, cust_payload: Dict[str, Any]
) -> Customer:
    """
    Match SuSoft-customer mot lokal kunde via `susoft_customer_id`.
    Hvis ingen match → opprett en minimal kunde slik at ordren kan lagres.
    """
    susoft_id = cust_payload.get("id")
    if susoft_id is None or susoft_id == "":
        return _get_or_create_unknown_customer(db, tenant_id)

    susoft_id_str = str(susoft_id)
    customer = db.execute(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.susoft_customer_id == susoft_id_str,
        )
    ).scalar_one_or_none()
    if customer:
        return customer

    # Bygg minimal kunde fra payload (full sync vil oppdatere senere).
    first = (cust_payload.get("firstName") or "").strip()
    last = (cust_payload.get("lastName") or "").strip()
    display = (cust_payload.get("displayName") or "").strip()
    name = display or (f"{first} {last}".strip()) or f"Kunde {susoft_id_str}"

    customer = Customer(
        tenant_id=tenant_id,
        susoft_customer_id=susoft_id_str,
        name=name[:255],
        company_name=display[:255] if cust_payload.get("isCompany") and display else None,
        contact_person=first[:255] if first else None,
        email=(cust_payload.get("email") or None),
        phone=(cust_payload.get("phone") or None),
        country="Norway",
        is_active=True,
        order_lead_days=14,
    )
    db.add(customer)
    db.flush()
    logger.info(
        "Opprettet ny kunde fra SuSoft-ordre (tenant=%s, susoft_id=%s, name=%r)",
        tenant_id, susoft_id_str, customer.name,
    )
    return customer


def _resolve_product(
    db: Session, tenant_id: int, line: Dict[str, Any]
) -> Optional[Product]:
    """Slå opp lokalt produkt via SuSoft productId. None hvis ikke funnet."""
    prod_block = line.get("product") or {}
    pid = prod_block.get("id") or line.get("productId")
    if pid is None or pid == "":
        return None
    return db.execute(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.susoft_product_id == str(pid),
        )
    ).scalar_one_or_none()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _map_status(row: Dict[str, Any]) -> OrderStatus:
    """Map SuSoft `type` + `statusName` til vår OrderStatus."""
    if (row.get("type") or "").upper() == "CART":
        return OrderStatus.DRAFT
    status = (row.get("statusName") or "").strip().lower()
    if status in ("confirmed", "bekreftet", "klar for leveranse", "ready"):
        return OrderStatus.CONFIRMED
    if status in ("delivered", "levert"):
        return OrderStatus.DELIVERED
    if status in ("cancelled", "canceled", "avbrutt", "kansellert"):
        return OrderStatus.CANCELLED
    if status in ("in_transit", "i transport", "på vei"):
        return OrderStatus.IN_TRANSIT
    # Default: behold som confirmed for ORDER, draft for alt annet
    if (row.get("type") or "").upper() == "ORDER":
        return OrderStatus.CONFIRMED
    return OrderStatus.DRAFT


# ---------------------------------------------------------------------------
# Hovedfunksjon
# ---------------------------------------------------------------------------

def ingest_susoft_orders_for_tenant(
    db: Session,
    tenant_id: int,
    days_back: int = DEFAULT_POLL_DAYS_BACK,
    shop_id: Optional[str] = None,
) -> Dict[str, int]:
    """
    Pull ordrer fra SuSoft og opprett lokalt for de som mangler.

    Returnerer summary: {fetched, created, skipped_existing, errors}.
    """
    today = date.today()
    date_from = today - timedelta(days=days_back)
    date_to = today + timedelta(days=days_back)  # inkluder fremtidige bestillinger

    service = SuSoftService(db, tenant_id=tenant_id)

    try:
        rows = service.list_orders(
            date_from=date_from,
            date_to=date_to,
            shop_id=shop_id,
            mode="FULL",
        )
    except SuSoftAPIError as e:
        logger.error("SuSoft list_orders feilet (tenant=%s): %s", tenant_id, e)
        return {"fetched": 0, "created": 0, "skipped_existing": 0, "errors": 1}

    summary = {
        "fetched": len(rows),
        "created": 0,
        "skipped_existing": 0,
        "errors": 0,
    }

    for row in rows:
        try:
            uuid_val = row.get("uuid")
            if not uuid_val:
                # Uten uuid kan vi ikke dedupere — hopp over.
                logger.debug("Hopper over SuSoft-rad uten uuid (orderNo=%s)", row.get("orderNo"))
                continue
            uuid_str = str(uuid_val)
            order_no_str = str(row.get("orderNo") or "") or None
            alt_id_raw = row.get("alternativeId")
            alt_order_uuid, legacy_order_id = _extract_local_order_refs_from_alt_id(
                alt_id_raw,
                tenant_id,
            )

            # Dedup-strategi:
            # 1) Match på susoft_uuid (vanlig pull-flow).
            # 2) Match på alternativeId == lokal Order.order_uuid (nytt format)
            #    eller tidligere tenant-prefikset Order.id-format. Denne raden
            #    er da SuSoft sin projeksjon av en ordre VI sendte opp, og skal
            #    linkes i stedet for å opprette duplikat.
            # 3) Match på susoft_order_id == orderNo (fallback hvis altId
            #    mangler men vi har stemplet orderNo lokalt).
            existing_order: Optional[Order] = None
            existing_id = db.execute(
                select(Order.id).where(
                    Order.tenant_id == tenant_id,
                    Order.susoft_uuid == uuid_str,
                )
            ).scalar_one_or_none()
            if existing_id:
                summary["skipped_existing"] += 1
                continue

            if alt_order_uuid is not None:
                existing_order = db.execute(
                    select(Order).where(
                        Order.tenant_id == tenant_id,
                        Order.order_uuid == alt_order_uuid,
                    )
                ).scalar_one_or_none()
            if existing_order is None and legacy_order_id is not None:
                existing_order = db.execute(
                    select(Order).where(
                        Order.tenant_id == tenant_id,
                        Order.id == legacy_order_id,
                    )
                ).scalar_one_or_none()
            if existing_order is None and order_no_str:
                existing_order = db.execute(
                    select(Order).where(
                        Order.tenant_id == tenant_id,
                        Order.susoft_order_id == order_no_str,
                    )
                ).scalar_one_or_none()
            if existing_order is not None:
                # Link projeksjonen til den lokale ordren (idempotent stempling).
                if not existing_order.susoft_uuid:
                    existing_order.susoft_uuid = uuid_str
                if order_no_str and not existing_order.susoft_order_no:
                    existing_order.susoft_order_no = order_no_str[:100]
                if order_no_str and not existing_order.susoft_order_id:
                    existing_order.susoft_order_id = order_no_str
                # Vis SuSoft orderNo som ordre-ID i UI for direkte sporbarhet.
                if order_no_str and (
                    not existing_order.order_no_display
                    or existing_order.order_no_display.startswith("APOS-CART-")
                ):
                    existing_order.order_no_display = f"APOS-{order_no_str}"[:50]
                db.commit()
                summary["skipped_existing"] += 1
                continue

            # Finn / opprett kunde
            cust_payload = row.get("customer") or {}
            if not isinstance(cust_payload, dict) or not cust_payload:
                customer = _get_or_create_unknown_customer(db, tenant_id)
            else:
                customer = _find_or_create_customer_from_payload(db, tenant_id, cust_payload)

            # Velg fulfillment-tid
            fulfill_dt, fulfill_kind = pick_susoft_fulfillment(row)
            # SuSoft bruker `orderDateTime` (ikke `orderDate`); behold fallback for bakoverkompat.
            order_dt = parse_susoft_datetime(
                row.get("orderDateTime") or row.get("orderDate")
            )
            pickup_dt = parse_susoft_datetime(row.get("pickupDate"))
            delivery_dt = parse_susoft_datetime(row.get("deliveryDate"))

            # delivery_date er NOT NULL i vår modell — fall tilbake til orderDate eller i dag
            chosen_dt = fulfill_dt or order_dt
            local_delivery_date: date = chosen_dt.date() if chosen_dt else today

            status = _map_status(row)

            _orderno_display = (
                f"APOS-{order_no_str}"[:50] if order_no_str else f"APOS-CART-{uuid_str[:8]}"
            )
            order = Order(
                tenant_id=tenant_id,
                customer_id=customer.id,
                delivery_date=local_delivery_date,
                status=status,
                sync_status=SyncStatus.SYNCED,  # Allerede i SuSoft per def
                susoft_uuid=uuid_str,
                susoft_order_no=str(row.get("orderNo") or "")[:100] or None,
                order_no_display=_orderno_display,
                susoft_shop_id=str(row.get("_shopId") or "")[:50] or None,
                susoft_pickup_at=pickup_dt,
                susoft_delivery_at=delivery_dt,
                susoft_fulfillment_type=fulfill_kind,
                susoft_raw_payload=row,
                source="susoft_import",
                customer_notes=(row.get("note") or row.get("comment") or None),
            )
            db.add(order)
            db.flush()  # få order.id

            # Linjer
            total_excl = Decimal("0.00")
            total_vat = Decimal("0.00")
            total_incl = Decimal("0.00")

            for line in (row.get("lines") or []):
                if not isinstance(line, dict):
                    continue
                product = _resolve_product(db, tenant_id, line)
                if product is None:
                    # Hopp over linjer der vi ikke kjenner produktet —
                    # ordren lagres uten dem (raw_payload har full info).
                    logger.warning(
                        "Ukjent produkt i SuSoft-ordre uuid=%s, productId=%s",
                        uuid_str, (line.get("product") or {}).get("id"),
                    )
                    continue

                qty = int(_to_decimal(line.get("quantity"), "0"))
                if qty <= 0:
                    continue
                vat_rate = _to_decimal(line.get("vatPercent") or product.vat_rate, "0")
                # SuSoft `price` er INKL. mva — konverter til ekskl. for lokal lagring.
                # Foretrekk netTotal/qty hvis tilgjengelig (mer presis enn omvendt-regning).
                net_total = line.get("netTotal")
                if net_total is not None and qty:
                    unit_price = (_to_decimal(net_total, "0") / Decimal(qty)).quantize(Decimal("0.0001"))
                else:
                    incl_price = _to_decimal(
                        line.get("netPrice") or line.get("unitPrice") or line.get("price"),
                        "0",
                    )
                    if vat_rate and vat_rate != 0:
                        unit_price = (incl_price / (Decimal("1") + vat_rate / Decimal("100"))).quantize(Decimal("0.0001"))
                    else:
                        unit_price = incl_price
                line_excl = (Decimal(qty) * unit_price).quantize(Decimal("0.01"))
                line_vat = (line_excl * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
                line_incl = (line_excl + line_vat).quantize(Decimal("0.01"))

                ol = OrderLine(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    product_id=product.id,
                    quantity=qty,
                    unit_price=unit_price,
                    vat_rate=vat_rate,
                    line_amount_excl_vat=line_excl,
                    line_vat=line_vat,
                    line_amount_incl_vat=line_incl,
                )
                db.add(ol)
                total_excl += line_excl
                total_vat += line_vat
                total_incl += line_incl

            order.total_amount_excl_vat = total_excl
            order.total_vat = total_vat
            order.total_amount_incl_vat = total_incl

            db.commit()
            summary["created"] += 1

        except Exception as e:
            db.rollback()
            summary["errors"] += 1
            logger.exception(
                "Feil ved ingest av SuSoft-ordre uuid=%s: %s",
                row.get("uuid"), e,
            )

    logger.info(
        "SuSoft ingest tenant=%s: fetched=%d created=%d skipped=%d errors=%d",
        tenant_id, summary["fetched"], summary["created"],
        summary["skipped_existing"], summary["errors"],
    )
    return summary


def ingest_susoft_orders_all_tenants(days_back: int = DEFAULT_POLL_DAYS_BACK) -> Dict[str, Any]:
    """
    Kjør ingest for alle tenants som har SuSoft-credentials konfigurert.
    """
    from ..auth_models import Tenant

    db = SessionLocal()
    results: Dict[str, Any] = {"tenants": []}
    try:
        tenants = db.execute(
            select(Tenant).where(Tenant.susoft_login.isnot(None))
        ).scalars().all()
        for tenant in tenants:
            try:
                summary = ingest_susoft_orders_for_tenant(
                    db, tenant_id=tenant.id, days_back=days_back
                )
                results["tenants"].append({
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    **summary,
                })
            except Exception as e:
                logger.exception("Ingest feilet for tenant %s: %s", tenant.id, e)
                results["tenants"].append({
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "error": str(e),
                })
    finally:
        db.close()
    return results


# ---------------------------------------------------------------------------
# ADMIN-API ("API 2") -- aPOS-CART-er
# ---------------------------------------------------------------------------
#
# /admin/order/list returnerer CART-er UTEN linjer. For hver cart må vi hente
# /shopping-cart/uuid for å få linjene. SuSoftService.list_admin_carts_with_details
# gjør begge kall og legger detaljen på `_detail`-nøkkelen.
#
# Numerisk status-mapping (observert):
#   0 = aktiv/ny CART
#   2 = lukket/konvertert CART
# Vi behandler alle som DRAFT siden de fortsatt er i CART-tilstand i SuSoft.

DEFAULT_ADMIN_CART_DAYS_BACK = 30


def _line_qty(line: Dict[str, Any]) -> int:
    """
    Hent antall fra en SuSoft-linje.

    Feltene varierer mellom endepunktene:
      - cart-detalj (admin /cart/{id})        : `qty`
      - cart-detalj (alternativ representasjon): `qtyOrdered` / `qtyDelivered`
      - ordre-linjer (/order/list)            : `quantity`
    """
    raw = (
        line.get("qty")
        if line.get("qty") is not None
        else line.get("qtyOrdered")
        if line.get("qtyOrdered") is not None
        else line.get("quantity")
    )
    return int(_to_decimal(raw, "0"))


def _line_unit_price(line: Dict[str, Any], vat_rate: Optional[Decimal] = None) -> Decimal:
    """
    Returner unit_price EKSKL. mva (slik vi lagrer lokalt).

    SuSoft cart-linjer (både admin /cart/{id} og /shopping-cart/uuid) bruker
    `price` = INKL. mva. Forskjellen er kun hvilke totaler de leverer:

    - Admin /cart/{id}: `netPrice` (ekskl per stk), `netTotal` (qty*excl),
      `total` (qty*incl), `vatAmount`.
    - /shopping-cart/uuid: `priceInclTax` (= price), `lineTotal` (qty*incl),
      `lineTaxAmount` (mva-beløp). INGEN netTotal/netPrice.

    Mest presist er å utlede ekskl. fra totaler (unngår avrundingsfeil per stk).
    Prioritet:
      1. (lineTotal - lineTaxAmount) / qty   — shopping-cart
      2. netTotal / qty                       — admin-cart
      3. netPrice                             — admin-cart
      4. price / (1+vat)                      — fallback
    """
    qty = _to_decimal(
        line.get("qty")
        or line.get("qtyOrdered")
        or line.get("quantity"),
        "0",
    )

    line_total = line.get("lineTotal")
    line_tax = line.get("lineTaxAmount")
    if line_total is not None and line_tax is not None and qty and qty != 0:
        excl_total = _to_decimal(line_total, "0") - _to_decimal(line_tax, "0")
        return (excl_total / qty).quantize(Decimal("0.0001"))

    net_total = line.get("netTotal")
    if net_total is not None and qty and qty != 0:
        return (_to_decimal(net_total, "0") / qty).quantize(Decimal("0.0001"))

    if line.get("netPrice") is not None:
        return _to_decimal(line.get("netPrice"), "0").quantize(Decimal("0.0001"))

    # Siste utvei: price er INKL. mva, del på (1+vat)
    incl_price = _to_decimal(line.get("price") or line.get("priceInclTax") or line.get("unitPrice"), "0")
    vat = vat_rate if vat_rate is not None else _to_decimal(
        line.get("lineTaxPercent") or line.get("vatPercent"), "0"
    )
    if vat and vat != 0:
        return (incl_price / (Decimal("1") + vat / Decimal("100"))).quantize(Decimal("0.0001"))
    return incl_price


def _line_vat_rate(line: Dict[str, Any], product: Optional[Product]) -> Decimal:
    """Cart-linjer bruker `lineTaxPercent`."""
    raw = (
        line.get("lineTaxPercent")
        or line.get("vatPercent")
        or (product.vat_rate if product else None)
    )
    return _to_decimal(raw, "0")


def _merge_admin_cart_row(admin_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Bygg én normalisert "ordre-rad" ved å flette admin-listen + cart-detalj.
    Detaljen vinner ved konflikt på datetime-felter (har høyere oppløsning).
    """
    detail = admin_row.get("_detail") or {}
    merged: Dict[str, Any] = dict(admin_row)
    # Detail har bedre data for kunde, datoer, og linjer
    if isinstance(detail.get("customer"), dict):
        # Kombiner: detail har displayName/address/isActive, admin har email i nested address
        merged_customer = dict(admin_row.get("customer") or {})
        merged_customer.update(detail["customer"])
        merged["customer"] = merged_customer
    if detail.get("orderDateTime"):
        merged["orderDateTime"] = detail["orderDateTime"]
    if detail.get("deliveryDateTime"):
        merged["deliveryDateTime"] = detail["deliveryDateTime"]
    if detail.get("lines"):
        merged["lines"] = detail["lines"]
    return merged


def _compute_cart_hash(merged_row: Dict[str, Any]) -> str:
    """
    Bygger en stabil hash av sync-relevante felt fra en SuSoft-cart.

    Brukes til å oppdage at SuSoft har endret carten siden forrige pull,
    uten at vi trenger en `lastModified`-stempel (som SuSoft ikke gir).

    Felt som inkluderes (alt annet er irrelevant for to-veis sync):
      - deliveryDate / pickupDate / deliveryDateTime
      - customerComment + ordre-level note
      - per-linje: productId, qtyOrdered, price, discountPercent, vatPercent, line.note
    """
    def _norm(v: Any) -> Any:
        if isinstance(v, Decimal):
            return f"{v:.4f}"
        if isinstance(v, float):
            return f"{v:.4f}"
        if v is None:
            return None
        return str(v)

    parts: Dict[str, Any] = {
        "deliveryDate": _norm(merged_row.get("deliveryDate")),
        "deliveryDateTime": _norm(merged_row.get("deliveryDateTime")),
        "pickupDate": _norm(merged_row.get("pickupDate")),
        "customerComment": _norm(merged_row.get("customerComment")),
        "note": _norm(merged_row.get("note")),
    }
    line_parts: List[Dict[str, Any]] = []
    for ln in merged_row.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        prod = ln.get("product") or {}
        line_parts.append({
            "productId": _norm(ln.get("productId") or prod.get("id")),
            "qty": _norm(ln.get("qtyOrdered") or ln.get("quantity")),
            "price": _norm(ln.get("price") or ln.get("netPrice")),
            "discountPercent": _norm(ln.get("discountPercent")),
            "vatPercent": _norm(ln.get("lineTaxPercent") or ln.get("vatPercent")),
            "note": _norm(ln.get("note")),
        })
    # Sorter linjer på productId+price slik at omsorting ikke teller som endring.
    line_parts.sort(key=lambda x: (str(x.get("productId") or ""), str(x.get("price") or "")))
    parts["lines"] = line_parts
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _build_order_lines_from_cart(
    db: Session,
    tenant_id: int,
    order_id: int,
    cart_lines: List[Dict[str, Any]],
) -> Tuple[List[OrderLine], Decimal, Decimal, Decimal]:
    """
    Bygg OrderLine-objekter fra SuSoft cart-linjer + returner totaler.

    NB: caller er ansvarlig for å `db.add()` linjene. Denne funksjonen
    flusher ikke. Linjer der produkt ikke finnes eller qty<=0 hoppes over.
    """
    lines_out: List[OrderLine] = []
    total_excl = Decimal("0.00")
    total_vat = Decimal("0.00")
    total_incl = Decimal("0.00")

    for line in cart_lines or []:
        if not isinstance(line, dict):
            continue
        product = _resolve_product(db, tenant_id, line)
        if product is None:
            logger.warning(
                "Ukjent produkt i SuSoft-cart order_id=%s, productId=%s",
                order_id, (line.get("product") or {}).get("id"),
            )
            continue
        qty = _line_qty(line)
        if qty <= 0:
            continue
        vat_rate = _line_vat_rate(line, product)
        unit_price = _line_unit_price(line, vat_rate)
        line_excl = (Decimal(qty) * unit_price).quantize(Decimal("0.01"))
        line_vat = (line_excl * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
        line_incl = (line_excl + line_vat).quantize(Decimal("0.01"))

        ol = OrderLine(
            tenant_id=tenant_id,
            order_id=order_id,
            product_id=product.id,
            quantity=qty,
            unit_price=unit_price,
            vat_rate=vat_rate,
            line_amount_excl_vat=line_excl,
            line_vat=line_vat,
            line_amount_incl_vat=line_incl,
        )
        lines_out.append(ol)
        total_excl += line_excl
        total_vat += line_vat
        total_incl += line_incl

    return lines_out, total_excl, total_vat, total_incl


def _refresh_cart_order_from_susoft(
    db: Session,
    tenant_id: int,
    order: Order,
    merged_row: Dict[str, Any],
    new_hash: str,
) -> None:
    """
    Oppdater en eksisterende DRAFT cart-import med nye data fra SuSoft.

    Dette er pull-siden av to-veis sync: når SuSoft sin cart har endret
    seg (hash != stored), erstatter vi linjer + datoer + notater lokalt.

    Caller har allerede sjekket:
      - order.status == DRAFT
      - order.susoft_pending_push == False
      - order.susoft_payload_hash != new_hash
    """
    delivery_dt = parse_susoft_datetime(
        merged_row.get("deliveryDateTime") or merged_row.get("deliveryDate")
    )
    pickup_dt = parse_susoft_datetime(merged_row.get("pickupDate"))
    if pickup_dt is not None:
        fulfill_dt, fulfill_kind = pickup_dt, "pickup"
    elif delivery_dt is not None:
        fulfill_dt, fulfill_kind = delivery_dt, "delivery"
    else:
        fulfill_dt, fulfill_kind = None, "unknown"

    chosen_dt = fulfill_dt
    if chosen_dt is not None:
        order.delivery_date = chosen_dt.date()
    order.susoft_pickup_at = pickup_dt
    order.susoft_delivery_at = delivery_dt
    order.susoft_fulfillment_type = fulfill_kind

    note = merged_row.get("note") or ""
    customer_comment = merged_row.get("customerComment") or ""
    order.customer_notes = "\n".join(
        s for s in (customer_comment.strip(), note.strip()) if s
    ) or None

    # Slett gamle linjer
    db.query(OrderLine).filter(
        OrderLine.tenant_id == tenant_id,
        OrderLine.order_id == order.id,
    ).delete(synchronize_session=False)
    db.flush()

    new_lines, total_excl, total_vat, total_incl = _build_order_lines_from_cart(
        db, tenant_id, order.id, merged_row.get("lines") or []
    )
    for ol in new_lines:
        db.add(ol)

    order.total_amount_excl_vat = total_excl
    order.total_vat = total_vat
    order.total_amount_incl_vat = total_incl
    order.susoft_raw_payload = merged_row
    order.susoft_payload_hash = new_hash


def ingest_susoft_admin_carts_for_tenant(
    db: Session,
    tenant_id: int,
    days_back: int = DEFAULT_ADMIN_CART_DAYS_BACK,
    shop_id: Optional[int] = None,
    type_: str = "CART",
) -> Dict[str, int]:
    """
    Hent CART-er fra SuSoft admin-API ("API 2") og opprett lokalt for de som
    mangler. Dedup mot `orders.susoft_uuid` (samme nøkkel som /order/list).

    Returnerer: {fetched, created, skipped_existing, errors}.
    """
    today = date.today()
    date_from = today - timedelta(days=days_back)
    date_to = today + timedelta(days=days_back)

    service = SuSoftService(db, tenant_id=tenant_id)

    try:
        rows = service.list_admin_carts_with_details(
            date_from=date_from,
            date_to=date_to,
            type_=type_,
            shop_id=shop_id,
        )
    except SuSoftAPIError as e:
        logger.error(
            "SuSoft list_admin_carts feilet (tenant=%s): %s", tenant_id, e
        )
        return {"fetched": 0, "created": 0, "skipped_existing": 0, "errors": 1}

    summary = {
        "fetched": len(rows),
        "created": 0,
        "updated": 0,
        "skipped_existing": 0,
        "skipped_pending_push": 0,
        "skipped_non_draft": 0,
        "errors": 0,
    }

    for admin_row in rows:
        try:
            uuid_val = admin_row.get("uuid")
            if not uuid_val:
                logger.debug(
                    "Hopper over admin-rad uten uuid (orderNo=%s)",
                    admin_row.get("orderNo"),
                )
                continue
            uuid_str = str(uuid_val)

            row = _merge_admin_cart_row(admin_row)
            new_hash = _compute_cart_hash(row)

            existing_order = db.execute(
                select(Order).where(
                    Order.tenant_id == tenant_id,
                    Order.susoft_uuid == uuid_str,
                    Order.is_deleted == False,  # noqa: E712
                )
            ).scalar_one_or_none()

            if existing_order is not None:
                # Pull-side oppdatering (to-veis sync):
                #   - Hopp over hvis lokal har ventende push (push vinner).
                #   - Hopp over hvis lokal status ikke er DRAFT (lokal "tatt over").
                #   - Hopp over hvis hash matcher (ingen endring i SuSoft).
                #   - Ellers: oppdater lokalt fra SuSoft.
                if existing_order.susoft_pending_push:
                    summary["skipped_pending_push"] += 1
                    continue
                if existing_order.status != OrderStatus.DRAFT:
                    summary["skipped_non_draft"] += 1
                    continue
                if existing_order.susoft_payload_hash == new_hash:
                    summary["skipped_existing"] += 1
                    continue
                _refresh_cart_order_from_susoft(
                    db, tenant_id, existing_order, row, new_hash
                )
                db.commit()
                summary["updated"] += 1
                logger.info(
                    "SuSoft cart oppdatert lokalt: order_id=%s uuid=%s",
                    existing_order.id, uuid_str,
                )
                continue

            # Finn / opprett kunde
            cust_payload = row.get("customer") or {}
            if not isinstance(cust_payload, dict) or not cust_payload:
                customer = _get_or_create_unknown_customer(db, tenant_id)
            else:
                customer = _find_or_create_customer_from_payload(
                    db, tenant_id, cust_payload
                )

            order_dt = parse_susoft_datetime(
                row.get("orderDateTime") or row.get("orderDate")
            )
            delivery_dt = parse_susoft_datetime(
                row.get("deliveryDateTime") or row.get("deliveryDate")
            )
            pickup_dt = parse_susoft_datetime(row.get("pickupDate"))

            # Velg fulfillment: pickup foretrekkes, ellers delivery
            if pickup_dt is not None:
                fulfill_dt, fulfill_kind = pickup_dt, "pickup"
            elif delivery_dt is not None:
                fulfill_dt, fulfill_kind = delivery_dt, "delivery"
            else:
                fulfill_dt, fulfill_kind = None, "unknown"

            chosen_dt = fulfill_dt or order_dt
            local_delivery_date: date = chosen_dt.date() if chosen_dt else today

            # CART -> alltid DRAFT (uavhengig av numerisk status)
            status = OrderStatus.DRAFT

            # Notater: admin-listen har note + customerComment.
            note = row.get("note") or ""
            customer_comment = row.get("customerComment") or ""
            customer_notes = "\n".join(
                s for s in (customer_comment.strip(), note.strip()) if s
            ) or None

            _admin_orderno = str(row.get("orderNo") or "") or None
            _admin_display = (
                f"APOS-{_admin_orderno}"[:50] if _admin_orderno else f"APOS-CART-{uuid_str[:8]}"
            )
            order = Order(
                tenant_id=tenant_id,
                customer_id=customer.id,
                delivery_date=local_delivery_date,
                status=status,
                sync_status=SyncStatus.SYNCED,
                susoft_uuid=uuid_str,
                susoft_order_no=str(row.get("orderNo") or "")[:100] or None,
                order_no_display=_admin_display,
                susoft_shop_id=str(row.get("shopId") or row.get("_shopId") or "")[:50] or None,
                susoft_pickup_at=pickup_dt,
                susoft_delivery_at=delivery_dt,
                susoft_fulfillment_type=fulfill_kind,
                susoft_raw_payload=row,
                susoft_payload_hash=new_hash,
                source="susoft_cart_import",
                customer_notes=customer_notes,
            )
            db.add(order)
            db.flush()

            new_lines, total_excl, total_vat, total_incl = _build_order_lines_from_cart(
                db, tenant_id, order.id, row.get("lines") or []
            )
            for ol in new_lines:
                db.add(ol)

            order.total_amount_excl_vat = total_excl
            order.total_vat = total_vat
            order.total_amount_incl_vat = total_incl

            db.commit()
            summary["created"] += 1

        except Exception as e:
            db.rollback()
            summary["errors"] += 1
            logger.exception(
                "Feil ved ingest av SuSoft-cart uuid=%s: %s",
                admin_row.get("uuid"), e,
            )

    logger.info(
        "SuSoft admin-cart ingest tenant=%s: fetched=%d created=%d updated=%d "
        "skipped_unchanged=%d skipped_pending=%d skipped_non_draft=%d errors=%d",
        tenant_id, summary["fetched"], summary["created"], summary["updated"],
        summary["skipped_existing"], summary["skipped_pending_push"],
        summary["skipped_non_draft"], summary["errors"],
    )
    return summary


def ingest_susoft_admin_carts_all_tenants(
    days_back: int = DEFAULT_ADMIN_CART_DAYS_BACK,
) -> Dict[str, Any]:
    """Kjør admin-cart-ingest for alle tenants med admin-credentials konfigurert."""
    from ..auth_models import Tenant

    db = SessionLocal()
    results: Dict[str, Any] = {"tenants": []}
    try:
        tenants = db.execute(
            select(Tenant).where(
                Tenant.susoft_admin_login.isnot(None),
                Tenant.susoft_admin_password_encrypted.isnot(None),
            )
        ).scalars().all()
        for tenant in tenants:
            try:
                summary = ingest_susoft_admin_carts_for_tenant(
                    db, tenant_id=tenant.id, days_back=days_back
                )
                results["tenants"].append({
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    **summary,
                })
            except Exception as e:
                logger.exception(
                    "Admin-cart-ingest feilet for tenant %s: %s", tenant.id, e
                )
                results["tenants"].append({
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "error": str(e),
                })
    finally:
        db.close()
    return results


"""
Push-side av to-veis SuSoft-cart-sync.

Når en lokal cart-import-ordre (status DRAFT, source="susoft_cart_import")
endres lokalt — qty, linjer lagt til/fjernet, dato eller notater — speiles
endringen tilbake til SuSoft via `PUT /admin/order/uuid/{uuid}`.

Strategi:

1. Hent FERSK admin-payload fra SuSoft (`get_admin_order_detail`). Dette
   gir oss et komplett payload-skjema (med kunde, currency, source osv.)
   som vi kan patche utvalgte felt i, slik at vi ikke ved et uhell sletter
   data SuSoft har som vi ikke speiler lokalt.
2. Patch inn lokale endringer:
     - `lines`  →  bygges fra lokale `OrderLine`-rader, ett produkt per linje
     - `deliveryDateTime` / `pickupDate` → fra lokale dato-felt
     - `customerComment` → fra lokal `customer_notes` (hele teksten)
3. PUT tilbake.
4. Ved suksess:
     - `susoft_pending_push = False`
     - `susoft_last_push_at = now`
     - `susoft_last_push_error = None`
     - `susoft_admin_payload = <ny payload>`
     - `susoft_payload_hash = hash(merged_row utledet fra ny payload)`
       (slik at neste pull ikke ser dette som "endret i SuSoft" og ruller
       tilbake våre egne endringer.)
5. Ved feil: behold `susoft_pending_push=True`, lagre feilmeldingen.
   Sweeper (Celery) prøver igjen senere.

NB: Vi pusher *ikke* hvis ordren ikke er DRAFT lenger, eller hvis den ikke
har noe susoft_uuid. Caller bør sjekke dette først, men vi dobbel-sjekker
her som safety net.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Order, OrderLine, OrderStatus, Product
from ..time_utils import now_utc, to_naive_utc
from .susoft import SuSoftAPIError, SuSoftService
from .susoft_ingest import _compute_cart_hash, _merge_admin_cart_row

logger = logging.getLogger(__name__)


def _format_susoft_dt(dt: Optional[datetime]) -> Optional[str]:
    """SuSoft cart-payload bruker ISO-8601 uten tidssone (`YYYY-MM-DDTHH:MM:SS`)."""
    if dt is None:
        return None
    # Strip tzinfo hvis den finnes — SuSoft forventer naive lokal-tid.
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _line_dict_for_susoft(
    line: OrderLine,
    product: Product,
    line_no: int,
    template_line: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Bygg én SuSoft cart-line-dict fra lokal `OrderLine`.

    `template_line` (valgfri) brukes hvis vi har en eksisterende SuSoft-linje
    for samme produkt — da bevarer vi felt vi ikke styrer (costPriceInclTax,
    discountRoundingMode, source, priceRef, created osv.).
    """
    qty = float(line.quantity)
    price = float(line.unit_price)
    vat_pct = float(line.vat_rate)
    price_incl = round(price * (1 + vat_pct / 100.0), 4)
    line_total = round(price * qty, 4)
    line_tax = round(line_total * vat_pct / 100.0, 4)

    base: Dict[str, Any] = dict(template_line) if template_line else {}
    base.update({
        "lineNo": line_no,
        "product": {
            "id": product.susoft_product_id or product.sku or str(product.id),
            "barcode": (
                (template_line or {}).get("product", {}).get("barcode")
                or product.susoft_product_id
                or product.sku
            ),
        },
        "text": product.name,
        "qty": qty,
        "price": price,
        "priceInclTax": price_incl,
        "lineTaxPercent": vat_pct,
        "lineTaxAmount": line_tax,
        "lineTotal": round(line_total + line_tax, 4),
        "discountPercent": float(getattr(line, "discount_percent", 0) or 0),
        "discountAmount": 0.0,
    })
    if line.notes:
        base["note"] = line.notes
    return base


def _build_put_payload(
    db: Session,
    order: Order,
    base_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Lag PUT-payload ved å patche `base_payload` (fersk fra SuSoft) med
    lokale verdier.
    """
    payload = dict(base_payload)  # shallow copy — vi erstatter top-level felt

    # Datoer
    if order.susoft_delivery_at is not None:
        payload["deliveryDateTime"] = _format_susoft_dt(order.susoft_delivery_at)
    if order.susoft_pickup_at is not None:
        payload["pickupDate"] = _format_susoft_dt(order.susoft_pickup_at)

    # Notater (lokal customer_notes går til customerComment)
    payload["customerComment"] = order.customer_notes or ""

    # Linjer — last produkter for alle lokale linjer
    local_lines: List[OrderLine] = list(order.lines or [])
    if not local_lines:
        # Refetch i tilfelle relasjonen ikke er loaded
        local_lines = (
            db.query(OrderLine)
            .filter(OrderLine.order_id == order.id, OrderLine.tenant_id == order.tenant_id)
            .all()
        )

    # Map gamle SuSoft-linjer per produktId så vi kan beholde immaterielle felt
    old_lines_by_pid: Dict[str, Dict[str, Any]] = {}
    for ln in base_payload.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        pid = (ln.get("product") or {}).get("id")
        if pid:
            old_lines_by_pid[str(pid)] = ln

    new_lines: List[Dict[str, Any]] = []
    for idx, ol in enumerate(local_lines, start=1):
        product = db.get(Product, ol.product_id)
        if product is None:
            logger.warning(
                "push_order_to_susoft: hopper over linje uten produkt order_id=%s line_id=%s",
                order.id, ol.id,
            )
            continue
        pid_key = product.susoft_product_id or product.sku or str(product.id)
        template = old_lines_by_pid.get(pid_key)
        new_lines.append(_line_dict_for_susoft(ol, product, idx, template))

    payload["lines"] = new_lines
    return payload


def push_order_to_susoft(
    db: Session,
    order: Order,
    *,
    service: Optional[SuSoftService] = None,
) -> Dict[str, Any]:
    """
    Push lokale endringer på en cart-import-ordre tilbake til SuSoft.

    Returnerer en summary-dict:
      {"status": "pushed"|"skipped"|"failed", "reason"?: str, "error"?: str}

    Caller er ansvarlig for å committe DB-endringene etter denne funksjonen.
    Ved unntak rolles ingenting tilbake automatisk her — vi setter felt på
    `order` så caller kan committe error-state også.
    """
    if order.source != "susoft_cart_import":
        return {"status": "skipped", "reason": "not_cart_import"}
    if not order.susoft_uuid:
        return {"status": "skipped", "reason": "no_uuid"}
    if order.status != OrderStatus.DRAFT:
        return {"status": "skipped", "reason": "not_draft"}

    svc = service or SuSoftService(db, tenant_id=order.tenant_id)

    try:
        base_payload = svc.get_admin_order_detail(order.susoft_uuid)
        if not base_payload:
            order.susoft_pending_push = True
            order.susoft_last_push_error = "Cart finnes ikke i SuSoft (404)"
            return {"status": "failed", "error": "not_found"}

        put_payload = _build_put_payload(db, order, base_payload)
        # Debug: log linje-summary (qty/price per produkt) for å verifisere hva vi sender
        try:
            line_summary = [
                {
                    "pid": (ln.get("product") or {}).get("id"),
                    "qty": ln.get("qty"),
                    "price": ln.get("price"),
                }
                for ln in (put_payload.get("lines") or [])
            ]
            logger.info(
                "SuSoft PUT-payload order_id=%s uuid=%s lines=%s deliveryDateTime=%s customerComment=%r",
                order.id, order.susoft_uuid, line_summary,
                put_payload.get("deliveryDateTime"), put_payload.get("customerComment"),
            )
        except Exception:  # noqa: BLE001
            pass
        result = svc.update_admin_order(order.susoft_uuid, put_payload)

        # Bruk responsen hvis den finnes, ellers vår egen patched payload
        new_state = result if (isinstance(result, dict) and result) else put_payload

        # Oppdater lokal sync-state
        order.susoft_admin_payload = new_state
        order.susoft_raw_payload = new_state
        # Beregn ny hash basert på det vi nettopp pushet — slik at neste
        # pull ikke ser dette som "endret i SuSoft".
        merged = _merge_admin_cart_row({**new_state, "_detail": new_state})
        order.susoft_payload_hash = _compute_cart_hash(merged)
        order.susoft_pending_push = False
        order.susoft_last_push_at = to_naive_utc(now_utc())
        order.susoft_last_push_error = None

        logger.info(
            "SuSoft push OK: order_id=%s uuid=%s lines=%d",
            order.id, order.susoft_uuid, len(put_payload.get("lines") or []),
        )
        return {"status": "pushed"}

    except SuSoftAPIError as e:
        order.susoft_pending_push = True
        order.susoft_last_push_error = str(e)[:500]
        logger.warning(
            "SuSoft push FAILED (API): order_id=%s uuid=%s: %s",
            order.id, order.susoft_uuid, e,
        )
        return {"status": "failed", "error": str(e)}
    except Exception as e:  # noqa: BLE001
        order.susoft_pending_push = True
        order.susoft_last_push_error = str(e)[:500]
        logger.exception(
            "SuSoft push FAILED (uventet): order_id=%s uuid=%s",
            order.id, order.susoft_uuid,
        )
        return {"status": "failed", "error": str(e)}


def retry_pending_pushes(db: Session, *, limit: int = 50) -> Dict[str, int]:
    """
    Sweeper for ordrer med `susoft_pending_push=True`.

    Brukes av Celery beat (commit D). Caller commit per ordre.
    """
    from sqlalchemy import select

    summary = {"attempted": 0, "pushed": 0, "failed": 0, "skipped": 0}
    rows = db.execute(
        select(Order)
        .where(
            Order.susoft_pending_push == True,  # noqa: E712
            Order.susoft_uuid.isnot(None),
            Order.is_deleted == False,  # noqa: E712
        )
        .limit(limit)
    ).scalars().all()

    for order in rows:
        summary["attempted"] += 1
        result = push_order_to_susoft(db, order)
        try:
            db.commit()
        except Exception:
            db.rollback()
            summary["failed"] += 1
            continue
        if result["status"] == "pushed":
            summary["pushed"] += 1
        elif result["status"] == "failed":
            summary["failed"] += 1
        else:
            summary["skipped"] += 1
    return summary

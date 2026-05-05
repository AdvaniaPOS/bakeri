"""
Reparer ordre fra `susoft_import` som mangler linjer.

Bygger linjer paa nytt fra lagret `susoft_raw_payload`. Brukes naar produktene
ble importert ETTER ordrene (slik at _resolve_product returnerte None ved
opprinnelig ingest og linjer ble hoppet over).

Bruk:
    python scripts/repair_susoft_order_lines.py --tenant-id 1
    python scripts/repair_susoft_order_lines.py --tenant-id 1 --dry-run
"""
import argparse
import logging
import sys
from decimal import Decimal
from typing import List

from app.database import SessionLocal
from app.models import Order, OrderLine, Product
from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("repair_susoft_orders")


def _to_decimal(value, default="0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _resolve_product(db, tenant_id: int, line: dict):
    pid = (line.get("product") or {}).get("id") or line.get("productId")
    if pid is None or pid == "":
        return None
    return db.execute(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.susoft_product_id == str(pid),
        )
    ).scalar_one_or_none()


def repair_order(db, order: Order, dry_run: bool = False) -> dict:
    payload = order.susoft_raw_payload or {}
    raw_lines = payload.get("lines") or []
    if not raw_lines:
        return {"order_id": order.id, "skipped": "no_lines_in_payload"}

    new_lines: List[OrderLine] = []
    total_excl = Decimal("0.00")
    total_vat = Decimal("0.00")
    total_incl = Decimal("0.00")
    skipped = 0

    for line in raw_lines:
        if not isinstance(line, dict):
            continue
        product = _resolve_product(db, order.tenant_id, line)
        if product is None:
            skipped += 1
            logger.warning(
                "  ordre %s: produkt mangler fortsatt: %s",
                order.id, (line.get("product") or {}).get("id"),
            )
            continue

        qty = int(_to_decimal(line.get("quantity") or line.get("qty"), "0"))
        if qty <= 0:
            continue

        vat_rate = _to_decimal(
            line.get("vatPercent")
            or line.get("lineTaxPercent")
            or product.vat_rate,
            "0",
        )

        # SuSoft `price` er INKL. mva. Foretrekk netTotal/qty hvis tilgjengelig.
        net_total = line.get("netTotal")
        if net_total is not None and qty:
            unit_price = (_to_decimal(net_total, "0") / Decimal(qty)).quantize(Decimal("0.0001"))
        else:
            incl_price = _to_decimal(
                line.get("netPrice")
                or line.get("unitPrice")
                or line.get("price"),
                "0",
            )
            if vat_rate and vat_rate != 0:
                unit_price = (incl_price / (Decimal("1") + vat_rate / Decimal("100"))).quantize(Decimal("0.0001"))
            else:
                unit_price = incl_price

        line_excl = (Decimal(qty) * unit_price).quantize(Decimal("0.01"))
        line_vat = (line_excl * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
        line_incl = (line_excl + line_vat).quantize(Decimal("0.01"))

        new_lines.append(OrderLine(
            tenant_id=order.tenant_id,
            order_id=order.id,
            product_id=product.id,
            quantity=qty,
            unit_price=unit_price,
            vat_rate=vat_rate,
            line_amount_excl_vat=line_excl,
            line_vat=line_vat,
            line_amount_incl_vat=line_incl,
        ))
        total_excl += line_excl
        total_vat += line_vat
        total_incl += line_incl

    if not new_lines:
        return {"order_id": order.id, "skipped": "no_resolvable_products", "missing": skipped}

    if dry_run:
        return {
            "order_id": order.id, "would_add_lines": len(new_lines),
            "missing": skipped, "total_incl": str(total_incl),
        }

    # Slett evt. eksisterende linjer (skal vaere 0, men trygg side)
    db.query(OrderLine).filter(
        OrderLine.tenant_id == order.tenant_id,
        OrderLine.order_id == order.id,
    ).delete(synchronize_session=False)
    db.flush()

    for ol in new_lines:
        db.add(ol)

    order.total_amount_excl_vat = total_excl
    order.total_vat = total_vat
    order.total_amount_incl_vat = total_incl

    return {
        "order_id": order.id, "added_lines": len(new_lines),
        "missing": skipped, "total_incl": str(total_incl),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--source", default="susoft_import",
        help="Filtrer paa source (default: susoft_import)",
    )
    args = ap.parse_args()

    db = SessionLocal()
    try:
        # Finn ordre uten linjer
        orders = db.query(Order).filter(
            Order.tenant_id == args.tenant_id,
            Order.source == args.source,
        ).all()

        repaired = 0
        skipped = 0
        for o in orders:
            line_count = db.query(OrderLine).filter(
                OrderLine.tenant_id == args.tenant_id,
                OrderLine.order_id == o.id,
            ).count()
            if line_count > 0:
                continue
            result = repair_order(db, o, dry_run=args.dry_run)
            logger.info("Ordre %s: %s", o.id, result)
            if "added_lines" in result or "would_add_lines" in result:
                repaired += 1
            else:
                skipped += 1

        if not args.dry_run:
            db.commit()
            logger.info("Commit OK. Reparert: %d. Hoppet over: %d.", repaired, skipped)
        else:
            logger.info("DRY-RUN. Ville reparert: %d. Hoppet over: %d.", repaired, skipped)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)

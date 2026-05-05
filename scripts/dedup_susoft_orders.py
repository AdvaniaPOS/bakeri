"""
Rydd opp i duplikat-ordrer som oppstod fordi pull-sync laget en ny lokal
ordre fra SuSoft sin /order-projeksjon etter at vi POST'et /order ved
fakturering av en cart-import.

Strategi:
  - Finn ordrer (B) der susoft_raw_payload->>'alternativeId' peker på en
    annen lokal Order.id (A) i samme tenant.
  - A er originalen (lokalt opprettet, evt. fra cart_import). B er duplikatet
    (laget av pull-sync).
  - Kopier susoft_uuid og susoft_order_id fra B → A hvis A mangler dem.
  - Marker B som is_deleted=True (soft delete) med en intern note.

Bruk:
    PYTHONPATH=. python scripts/dedup_susoft_orders.py --tenant-id 1 --dry-run
    PYTHONPATH=. python scripts/dedup_susoft_orders.py --tenant-id 1
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Order


def _alt_id(order: Order) -> Optional[int]:
    payload = order.susoft_raw_payload or {}
    raw = payload.get("alternativeId") if isinstance(payload, dict) else None
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Hent alle ikke-slettede ordrer for tenant
        orders = db.execute(
            select(Order).where(
                Order.tenant_id == args.tenant_id,
                Order.is_deleted == False,  # noqa: E712
            )
        ).scalars().all()

        by_id = {o.id: o for o in orders}

        merged = 0
        already_linked = 0
        skipped = 0

        for dup in orders:
            alt = _alt_id(dup)
            if alt is None:
                continue
            if alt == dup.id:
                continue  # peker på seg selv (egen sync)
            original = by_id.get(alt)
            if original is None:
                skipped += 1
                continue

            # Sjekk at vi ikke allerede har linket dem
            if original.susoft_uuid == dup.susoft_uuid and dup.is_deleted:
                already_linked += 1
                continue

            print(
                f"DUP: order_id={dup.id} (uuid={dup.susoft_uuid}, orderNo={dup.susoft_order_id}) "
                f"-> ORIGINAL order_id={original.id} "
                f"(uuid={original.susoft_uuid}, orderNo={original.susoft_order_id}, "
                f"invoice_no={original.susoft_invoice_no})"
            )

            if args.dry_run:
                merged += 1
                continue

            # Kopier SuSoft-stempler over til originalen hvis den mangler dem
            if not original.susoft_uuid and dup.susoft_uuid:
                original.susoft_uuid = dup.susoft_uuid
            if not original.susoft_order_id and dup.susoft_order_id:
                original.susoft_order_id = dup.susoft_order_id
            if not original.susoft_order_no and dup.susoft_order_no:
                original.susoft_order_no = dup.susoft_order_no

            # Marker duplikat som slettet
            dup.is_deleted = True
            note_prefix = f"[DEDUP] Auto-slettet duplikat av ordre #{original.id}. "
            existing_note = dup.internal_notes or ""
            if note_prefix not in existing_note:
                dup.internal_notes = (note_prefix + existing_note).strip()
            merged += 1

        if not args.dry_run:
            db.commit()

        print()
        print(f"Tenant {args.tenant_id}: {merged} duplikater {'ville blitt' if args.dry_run else ''} flettet/slettet, "
              f"{already_linked} allerede ryddet, {skipped} hoppet over (manglet original).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

"""
Diagnose og reparer aktiv/skjult-status på produkter mot Susoft.

Sjekker:
  1. Hvor mange produkter vi har lokalt (totalt / aktive / skjulte / overstyrt)
  2. Hvor mange Susoft returnerer (active=true / active=false / totalt)
  3. Lister produkter som er aktive lokalt men inaktive i Susoft (det som
     er for mange i "aktive"-listen din)
  4. Lister produkter Susoft har, men vi mangler

Bruk:
  # Bare rapport (ingen endringer):
  python -m scripts.audit_product_active --tenant-id 1

  # Reparer: tving Susoft-active til å overskrive lokal status,
  # og nullstill alle is_active_overridden flagg så Susoft blir fasit:
  python -m scripts.audit_product_active --tenant-id 1 --apply

  # Re-sync først, så reparer:
  python -m scripts.audit_product_active --tenant-id 1 --resync --apply
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Set

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Product
from app.services.susoft import SuSoftService


def _local_counts(db, tenant_id: int) -> Dict[str, int]:
    total = db.execute(
        select(func.count(Product.id)).where(Product.tenant_id == tenant_id)
    ).scalar() or 0
    active = db.execute(
        select(func.count(Product.id)).where(
            Product.tenant_id == tenant_id, Product.is_active == True  # noqa: E712
        )
    ).scalar() or 0
    overridden = db.execute(
        select(func.count(Product.id)).where(
            Product.tenant_id == tenant_id,
            Product.is_active_overridden == True,  # noqa: E712
        )
    ).scalar() or 0
    return {"total": total, "active": active, "inactive": total - active, "overridden": overridden}


def _fetch_susoft_products(svc: SuSoftService) -> List[dict]:
    return svc._fetch_paginated_product_search()


def _summarize_susoft(products: List[dict]) -> Dict[str, int]:
    seen: Set[str] = set()
    active = 0
    inactive = 0
    for p in products:
        pid = p.get("id")
        if pid is None or pid == "":
            continue
        pid = str(pid)
        if pid in seen:
            continue
        seen.add(pid)
        if bool(p.get("active", True)):
            active += 1
        else:
            inactive += 1
    return {"unique": len(seen), "active": active, "inactive": inactive, "raw_returned": len(products)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Skriv endringer til DB")
    parser.add_argument("--resync", action="store_true", help="Kjør sync_products_from_susoft først")
    parser.add_argument("--reset-overrides", action="store_true",
                        help="Nullstill is_active_overridden=false for ALLE produkter (Susoft blir fasit). Kun med --apply.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print(f"\n=== Tenant {args.tenant_id} ===")
        before = _local_counts(db, args.tenant_id)
        print(f"Lokalt FØR: total={before['total']}  aktive={before['active']}  "
              f"skjulte={before['inactive']}  overstyrt={before['overridden']}")

        svc = SuSoftService(db, tenant_id=args.tenant_id)

        if args.resync:
            print("\n>> Kjører full produkt-sync fra Susoft...")
            result = svc.sync_products_from_susoft()
            print(f"   Sync-resultat: {result}")

        print("\n>> Henter produkter fra Susoft for diagnose...")
        susoft_products = _fetch_susoft_products(svc)
        susoft = _summarize_susoft(susoft_products)
        print(f"Susoft: unike={susoft['unique']}  active=true={susoft['active']}  "
              f"active=false={susoft['inactive']}  (raw returned={susoft['raw_returned']})")

        # Bygg map susoft_id -> active
        susoft_active_map: Dict[str, bool] = {}
        for p in susoft_products:
            pid = p.get("id")
            if pid in (None, ""):
                continue
            susoft_active_map[str(pid)] = bool(p.get("active", True))

        susoft_ids = set(susoft_active_map.keys())

        # Hent alle lokale produkter
        local_products = db.execute(
            select(Product).where(Product.tenant_id == args.tenant_id)
        ).scalars().all()
        local_ids = {p.susoft_product_id for p in local_products if p.susoft_product_id}

        missing_locally = susoft_ids - local_ids
        missing_in_susoft = local_ids - susoft_ids

        print(f"\nMangler lokalt (finnes i Susoft, ikke hos oss): {len(missing_locally)}")
        if missing_locally and len(missing_locally) <= 50:
            print(f"   IDs: {sorted(missing_locally)}")

        print(f"Mangler i Susoft (finnes lokalt, ikke i Susoft): {len(missing_in_susoft)}")
        if missing_in_susoft and len(missing_in_susoft) <= 50:
            print(f"   IDs: {sorted(missing_in_susoft)}")

        # Diff: aktive lokalt men inaktive i Susoft
        wrongly_active: List[Product] = []
        wrongly_inactive: List[Product] = []
        for p in local_products:
            sid = p.susoft_product_id
            if not sid or sid not in susoft_active_map:
                continue
            susoft_ok = susoft_active_map[sid]
            if p.is_active and not susoft_ok:
                wrongly_active.append(p)
            elif not p.is_active and susoft_ok and not p.is_active_overridden:
                wrongly_inactive.append(p)

        print(f"\nFEIL aktive lokalt (Susoft sier inaktiv): {len(wrongly_active)}")
        for p in wrongly_active[:20]:
            print(f"   - [{p.susoft_product_id}] {p.name} (overstyrt={p.is_active_overridden})")
        if len(wrongly_active) > 20:
            print(f"   ... og {len(wrongly_active) - 20} til")

        print(f"\nFEIL skjulte lokalt (Susoft sier aktiv, ingen overstyring): {len(wrongly_inactive)}")
        for p in wrongly_inactive[:20]:
            print(f"   - [{p.susoft_product_id}] {p.name}")
        if len(wrongly_inactive) > 20:
            print(f"   ... og {len(wrongly_inactive) - 20} til")

        if args.apply:
            print("\n>> Skriver fix...")
            for p in wrongly_active:
                p.is_active = False
                p.is_active_overridden = False  # Susoft er fasit
            for p in wrongly_inactive:
                p.is_active = True
            if args.reset_overrides:
                reset = 0
                for p in local_products:
                    if p.is_active_overridden:
                        p.is_active_overridden = False
                        reset += 1
                print(f"   Nullstilte is_active_overridden på {reset} produkter")
            db.commit()
            after = _local_counts(db, args.tenant_id)
            print(f"\nLokalt ETTER: total={after['total']}  aktive={after['active']}  "
                  f"skjulte={after['inactive']}  overstyrt={after['overridden']}")
        else:
            print("\n(Tørr-kjøring — ingen endringer skrevet. Bruk --apply for å fikse.)")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

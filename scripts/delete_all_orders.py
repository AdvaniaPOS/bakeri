"""
Hard delete ALLE ordrer for en tenant. Sletter også ordrelinjer og amendments
via cascade (eller eksplisitt hvis cascade ikke er konfigurert).

ADVARSEL: Kan ikke angres. Ta backup først!

Bruk:
    PYTHONPATH=. python scripts/delete_all_orders.py --tenant-id 1 --dry-run
    PYTHONPATH=. python scripts/delete_all_orders.py --tenant-id 1 --yes
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import delete, select, func

from app.database import SessionLocal
from app import auth_models  # noqa: F401  -- registrer Tenant for FK-resolusjon
from app.models import Order, OrderLine, OrderAmendment


def _guard_production_delete() -> None:
    app_env = (os.getenv("APP_ENV") or "").strip().lower()
    if app_env in {"production", "prod", "staging"} and os.getenv("ALLOW_PROD_DELETE_ORDERS") != "YES_I_UNDERSTAND":
        print(
            "Refuserer aa hard-delete ordrer i production-liknende miljo. "
            "Sett ALLOW_PROD_DELETE_ORDERS=YES_I_UNDERSTAND hvis dette er bevisst.",
            file=sys.stderr,
        )
        sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Bekreft sletting (kreves uten --dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        order_ids = [
            r[0] for r in db.execute(
                select(Order.id).where(Order.tenant_id == args.tenant_id)
            ).all()
        ]
        n_orders = len(order_ids)

        if n_orders == 0:
            print(f"Tenant {args.tenant_id}: ingen ordrer å slette.")
            return 0

        n_lines = db.execute(
            select(func.count()).select_from(OrderLine).where(OrderLine.order_id.in_(order_ids))
        ).scalar() or 0
        n_amend = db.execute(
            select(func.count()).select_from(OrderAmendment).where(OrderAmendment.order_id.in_(order_ids))
        ).scalar() or 0

        print(f"Tenant {args.tenant_id}: vil slette {n_orders} ordrer, "
              f"{n_lines} ordrelinjer, {n_amend} amendments.")

        if args.dry_run:
            print("(dry-run, ingen sletting utført)")
            return 0

        _guard_production_delete()

        if not args.yes:
            print("Avbrutt. Kjør med --yes for å bekrefte.")
            return 1

        db.execute(delete(OrderAmendment).where(OrderAmendment.order_id.in_(order_ids)))
        db.execute(delete(OrderLine).where(OrderLine.order_id.in_(order_ids)))
        db.execute(delete(Order).where(Order.id.in_(order_ids)))
        db.commit()
        print(f"Slettet {n_orders} ordrer + {n_lines} linjer + {n_amend} amendments.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

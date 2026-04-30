"""
CLI: Generer ordrer fra aktive maler for alle (eller en spesifikk) tenant.

Kjøres typisk av cron daglig, f.eks. 02:05 lokal tid:

    5 2 * * * cd /home/poshubadmin/bakeri && /home/poshubadmin/bakeri/.venv/bin/python -m scripts.generate_orders --force >> /var/log/bakeri-generate.log 2>&1

Bruk:
    python -m scripts.generate_orders                    # alle aktive tenants, idempotent
    python -m scripts.generate_orders --force            # tving ny sjekk i dag
    python -m scripts.generate_orders --tenant-slug lampeland
"""
import argparse
import json
import sys
from datetime import datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.auth_models import Tenant
from app.api.orders import _run_ensure_horizon


def main() -> int:
    parser = argparse.ArgumentParser(description="Generer ordrer fra maler for alle aktive tenants.")
    parser.add_argument("--tenant-slug", help="Kjør kun for én tenant (slug)")
    parser.add_argument("--force", action="store_true", help="Tving kjøring selv om det allerede er gjort i dag")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = select(Tenant).where(
            Tenant.is_active == True,  # noqa: E712
            Tenant.is_deleted == False,  # noqa: E712
        )
        if args.tenant_slug:
            query = query.where(Tenant.slug == args.tenant_slug)
        tenants = db.execute(query).scalars().all()
    finally:
        db.close()

    if not tenants:
        print("Ingen aktive tenants funnet.", file=sys.stderr)
        return 1

    started = datetime.utcnow().isoformat()
    results = []

    for t in tenants:
        if args.force:
            # Nullstill stempel slik at run_ensure_horizon ikke hopper over
            db = SessionLocal()
            try:
                fresh = db.get(Tenant, t.id)
                if fresh is not None:
                    fresh.last_horizon_check_at = None
                    db.commit()
            finally:
                db.close()

        result = _run_ensure_horizon(t.id)
        result["tenant_slug"] = t.slug
        results.append(result)

    summary = {
        "started_at": started,
        "finished_at": datetime.utcnow().isoformat(),
        "tenants_processed": len(results),
        "results": results,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

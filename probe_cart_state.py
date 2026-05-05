"""
Debug-probe: hent en SuSoft cart via admin-API og skriv ut linjer + datoer.

Bruk:
    python probe_cart_state.py <uuid>            # bruk tenant 1
    python probe_cart_state.py <uuid> <tenant>   # spesifiser tenant
"""
import json
import sys

from app.database import SessionLocal
from app.services.susoft import SuSoftService


def main() -> None:
    if len(sys.argv) < 2:
        print("Bruk: python probe_cart_state.py <uuid> [tenant_id]")
        sys.exit(1)
    uuid = sys.argv[1]
    tenant_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    db = SessionLocal()
    try:
        svc = SuSoftService(db, tenant_id=tenant_id)
        body = svc.get_admin_order_detail(uuid)
        if body is None:
            print(f"Cart {uuid} ikke funnet (404)")
            return

        print("=== Top-level keys ===")
        print(sorted(body.keys()))
        print()
        print("uuid:        ", body.get("uuid"))
        print("orderNo:     ", body.get("orderNo"))
        print("status:      ", body.get("status"))
        print("orderDateTime:    ", body.get("orderDateTime"))
        print("deliveryDateTime: ", body.get("deliveryDateTime"))
        print("pickupDate:       ", body.get("pickupDate"))
        print("customerComment:  ", body.get("customerComment"))
        print("created:     ", body.get("created"))
        print("updated:     ", body.get("updated"))
        print()
        print("=== Lines ===")
        for ln in body.get("lines") or []:
            print(json.dumps(ln, indent=2, ensure_ascii=False))
            print("-" * 40)
    finally:
        db.close()


if __name__ == "__main__":
    main()

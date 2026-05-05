"""
Debug-probe: hent en SuSoft ordre via b\u00e5de admin-API og public order-API
for \u00e5 sammenligne feltene som styrer "klar for fakturering".

Bruk:
    python probe_invoice_state.py <uuid>            # tenant 1
    python probe_invoice_state.py <uuid> <tenant>
"""
import json
import sys

from app.database import SessionLocal
from app.services.susoft import SuSoftService


INVOICE_RELATED_KEYS = (
    "isForInvoicing",
    "forInvoicing",
    "invoiced",
    "isInvoiced",
    "invoicedDate",
    "invoiceNo",
    "status",
    "orderStatus",
    "state",
    "orderState",
    "type",
    "orderType",
    "isDraft",
    "draft",
    "isCart",
    "cart",
    "payments",
    "paid",
    "isPaid",
    "totalPaid",
    "totalToPay",
    "balance",
    "open",
    "closed",
    "cancelled",
    "deleted",
    "shopId",
    "uuid",
    "orderNo",
    "alternativeId",
    "deliveryDateTime",
    "orderDateTime",
)


def _summary(label, body):
    print(f"\n=== {label} ===")
    if body is None:
        print("(null / 404)")
        return
    if not isinstance(body, dict):
        print(f"(non-dict: {type(body).__name__})")
        print(json.dumps(body, indent=2, ensure_ascii=False)[:2000])
        return
    print("Top-level keys:", sorted(body.keys()))
    print()
    print("-- invoice-related felt --")
    for k in INVOICE_RELATED_KEYS:
        if k in body:
            v = body[k]
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)[:200]
            print(f"  {k}: {v}")
    print()
    print("-- FULL payload (klippet til 4000 tegn) --")
    print(json.dumps(body, indent=2, ensure_ascii=False)[:4000])


def main() -> None:
    if len(sys.argv) < 2:
        print("Bruk: python probe_invoice_state.py <uuid> [tenant_id]")
        sys.exit(1)
    uuid = sys.argv[1]
    tenant_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    db = SessionLocal()
    try:
        svc = SuSoftService(db, tenant_id=tenant_id)

        # 1) Admin-detaljer (samme som vi PUT-er)
        try:
            admin_body = svc.get_admin_order_detail(uuid)
        except Exception as e:  # noqa: BLE001
            admin_body = None
            print(f"[admin] feilet: {e}")
        _summary("ADMIN /admin/order/uuid/{uuid}", admin_body)

        # 2) Public order-by-uuid
        try:
            pub_body = svc.get_order_by_uuid(uuid)
        except Exception as e:  # noqa: BLE001
            pub_body = None
            print(f"[public] feilet: {e}")
        _summary("PUBLIC /order/uuid?uuid=", pub_body)

    finally:
        db.close()


if __name__ == "__main__":
    main()

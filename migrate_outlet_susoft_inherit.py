"""
Engangs-backfill: Sett `susoft_customer_id` p\u00e5 utsalg som mangler den,
ved \u00e5 arve fra hovedkunden (parent_customer_id).

Bakgrunn
--------
Utsalg opprettet f\u00f8r vi begynte \u00e5 arve hovedkundens SuSoft-ID arvet
ingenting og ville feile p\u00e5 push til SuSoft med "Customer has no SuSoft ID".
Denne scripten g\u00e5r gjennom alle utsalg per tenant og kopierer parent sin ID
hvis utsalget ikke har en egen. Idempotent og trygg \u00e5 kj\u00f8re flere ganger.

Bruk:
    python migrate_outlet_susoft_inherit.py
"""
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Customer


def main() -> None:
    db = SessionLocal()
    try:
        outlets = db.execute(
            select(Customer).where(
                Customer.parent_customer_id.is_not(None),
                Customer.is_deleted == False,  # noqa: E712
                (Customer.susoft_customer_id.is_(None))
                | (Customer.susoft_customer_id == ""),
            )
        ).scalars().all()

        updated = 0
        for outlet in outlets:
            parent = db.get(Customer, outlet.parent_customer_id)
            if not parent or not parent.susoft_customer_id:
                continue
            outlet.susoft_customer_id = parent.susoft_customer_id
            updated += 1
            print(
                f"  Utsalg {outlet.id} '{outlet.name}' "
                f"-> arver SuSoft-ID {parent.susoft_customer_id} fra hovedkunde {parent.id}"
            )

        if updated:
            db.commit()
            print(f"\nFerdig. Oppdaterte {updated} utsalg.")
        else:
            print("Ingen utsalg trengte oppdatering.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

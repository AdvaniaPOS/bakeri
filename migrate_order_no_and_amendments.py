"""
Idempotent migration:
1. Legg til orders.order_no_seq, orders.order_no_display, orders.reference
2. Legg til master_templates.default_reference
3. Backfill order_no_seq + order_no_display per tenant for eksisterende ordrer
4. Opprett tabell order_amendments (hvis mangler)
5. Opprett unique-indeks (tenant_id, order_no_seq)

Trygg aa kjore flere ganger.

Run:
    python migrate_order_no_and_amendments.py
"""
from __future__ import annotations

import sys
from collections import defaultdict

from sqlalchemy import text, inspect

from app.database import engine, SessionLocal
from app.models import Order, OrderAmendment, MasterTemplate
from app.auth_models import Tenant


def _column_exists(conn, table: str, column: str) -> bool:
    insp = inspect(conn)
    return any(c["name"] == column for c in insp.get_columns(table))


def _table_exists(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _slug_prefix(slug: str) -> str:
    """Tre-bokstav prefiks fra slug, store bokstaver. F.eks. 'lampeland-bakeri' -> 'LAM'."""
    cleaned = "".join(c for c in (slug or "") if c.isalnum()).upper()
    return (cleaned[:3] or "ORD").ljust(3, "X")


def main() -> int:
    print("=" * 60)
    print("Migrering: ordrenr-sekvens, referanse, amendments")
    print("=" * 60)

    with engine.begin() as conn:
        # 1. ALTER TABLE orders
        if not _column_exists(conn, "orders", "order_no_seq"):
            print("+ ALTER orders ADD COLUMN order_no_seq INTEGER")
            conn.execute(text("ALTER TABLE orders ADD COLUMN order_no_seq INTEGER"))
        else:
            print("= orders.order_no_seq finnes")

        if not _column_exists(conn, "orders", "order_no_display"):
            print("+ ALTER orders ADD COLUMN order_no_display VARCHAR(50)")
            conn.execute(text("ALTER TABLE orders ADD COLUMN order_no_display VARCHAR(50)"))
        else:
            print("= orders.order_no_display finnes")

        if not _column_exists(conn, "orders", "reference"):
            print("+ ALTER orders ADD COLUMN reference VARCHAR(255)")
            conn.execute(text("ALTER TABLE orders ADD COLUMN reference VARCHAR(255)"))
        else:
            print("= orders.reference finnes")

        # 2. ALTER TABLE master_templates
        if not _column_exists(conn, "master_templates", "default_reference"):
            print("+ ALTER master_templates ADD COLUMN default_reference VARCHAR(255)")
            conn.execute(text("ALTER TABLE master_templates ADD COLUMN default_reference VARCHAR(255)"))
        else:
            print("= master_templates.default_reference finnes")

    # 3. Opprett tabell order_amendments via metadata (idempotent)
    OrderAmendment.__table__.create(engine, checkfirst=True)
    print("= order_amendments tabell sjekket/opprettet")

    # 4. Backfill order_no_seq per tenant ordnet etter id
    print("\nBackfill ordrenr per tenant...")
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).all()
        for t in tenants:
            prefix = _slug_prefix(t.slug)
            # Hent alle ordrer som mangler seq, sortert etter id
            orders = (
                db.query(Order)
                .filter(Order.tenant_id == t.id, Order.order_no_seq.is_(None))
                .order_by(Order.id)
                .all()
            )
            if not orders:
                continue
            # Finn hoyeste eksisterende seq for denne tenant
            current_max = (
                db.query(Order.order_no_seq)
                .filter(Order.tenant_id == t.id, Order.order_no_seq.isnot(None))
                .order_by(Order.order_no_seq.desc())
                .limit(1)
                .scalar()
            ) or 0
            for o in orders:
                current_max += 1
                year = o.delivery_date.year if o.delivery_date else o.created_at.year
                o.order_no_seq = current_max
                o.order_no_display = f"{prefix}-{year}-{current_max:06d}"
            db.commit()
            print(f"  tenant {t.slug}: backfylt {len(orders)} ordrer (siste: {current_max})")
    finally:
        db.close()

    # 5. Opprett unique-indeks (tenant_id, order_no_seq)
    with engine.begin() as conn:
        existing = {row[0] for row in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )).fetchall()} if engine.dialect.name == "sqlite" else set()
        idx_name = "uq_order_tenant_seq"
        if idx_name not in existing:
            try:
                conn.execute(text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} "
                    f"ON orders (tenant_id, order_no_seq) WHERE order_no_seq IS NOT NULL"
                ))
                print(f"+ unique-indeks {idx_name}")
            except Exception as e:
                print(f"! kunne ikke opprette {idx_name}: {e}")
        else:
            print(f"= {idx_name} finnes")

    print("\nFerdig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

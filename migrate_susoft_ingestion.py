"""
Migrasjon: legg til kolonner på `orders` for SuSoft ORDRE-INGESTION
(polling FROM SuSoft hver 5. min — motsatt vei av eksisterende sync TIL SuSoft).

Nye kolonner:
- susoft_uuid              TEXT/VARCHAR(64)   — SuSoft sin uuid, dedup-nøkkel
- susoft_order_no          TEXT               — SuSoft ordrenummer (visning)
- susoft_shop_id           TEXT/VARCHAR(50)   — Shop/utsalg i SuSoft
- susoft_pickup_at         TIMESTAMP          — pickupDate fra SuSoft
- susoft_delivery_at       TIMESTAMP          — deliveryDate fra SuSoft
- susoft_fulfillment_type  TEXT               — pickup | delivery | unknown
- susoft_raw_payload       JSON/JSONB         — rå-rad fra SuSoft for audit
- source                   TEXT               — template | portal | manual | susoft_import

Pluss UNIQUE(tenant_id, susoft_uuid) for dedup.

Kjør på både SQLite (dev) og PostgreSQL (prod). Trygg å kjøre flere ganger.

Bruk:
    python migrate_susoft_ingestion.py
"""
from sqlalchemy import inspect, text

from app.database import engine


COLUMNS_PG = [
    ("susoft_uuid", "VARCHAR(64)"),
    ("susoft_order_no", "VARCHAR(100)"),
    ("susoft_shop_id", "VARCHAR(50)"),
    ("susoft_pickup_at", "TIMESTAMP"),
    ("susoft_delivery_at", "TIMESTAMP"),
    ("susoft_fulfillment_type", "VARCHAR(20)"),
    ("susoft_raw_payload", "JSONB"),
    ("source", "VARCHAR(30)"),
]

COLUMNS_SQLITE = [
    ("susoft_uuid", "TEXT"),
    ("susoft_order_no", "TEXT"),
    ("susoft_shop_id", "TEXT"),
    ("susoft_pickup_at", "TIMESTAMP"),
    ("susoft_delivery_at", "TIMESTAMP"),
    ("susoft_fulfillment_type", "TEXT"),
    ("susoft_raw_payload", "TEXT"),  # SQLite har ikke JSON-type
    ("source", "TEXT"),
]


def existing_columns(conn) -> set[str]:
    insp = inspect(conn)
    return {c["name"] for c in insp.get_columns("orders")}


def existing_indexes(conn) -> set[str]:
    insp = inspect(conn)
    names = set()
    for ix in insp.get_indexes("orders"):
        if ix.get("name"):
            names.add(ix["name"])
    return names


def existing_constraints(conn) -> set[str]:
    insp = inspect(conn)
    names = set()
    try:
        for uc in insp.get_unique_constraints("orders"):
            if uc.get("name"):
                names.add(uc["name"])
    except Exception:
        pass
    return names


def run() -> int:
    dialect = engine.dialect.name
    print(f"Dialect: {dialect}")

    cols = COLUMNS_PG if dialect == "postgresql" else COLUMNS_SQLITE

    with engine.begin() as conn:
        existing = existing_columns(conn)
        added = 0
        for name, col_type in cols:
            if name in existing:
                print(f"  [skip] kolonne {name} finnes allerede")
                continue
            print(f"  [add ] {name} {col_type}")
            conn.execute(text(f"ALTER TABLE orders ADD COLUMN {name} {col_type}"))
            added += 1

        # Indeks på susoft_uuid for raskt oppslag
        idx_names = existing_indexes(conn)
        if "ix_orders_susoft_uuid" not in idx_names:
            print("  [add ] index ix_orders_susoft_uuid")
            conn.execute(text(
                "CREATE INDEX ix_orders_susoft_uuid ON orders (susoft_uuid)"
            ))

        if "ix_orders_susoft_shop_id" not in idx_names:
            print("  [add ] index ix_orders_susoft_shop_id")
            conn.execute(text(
                "CREATE INDEX ix_orders_susoft_shop_id ON orders (susoft_shop_id)"
            ))

        if "ix_orders_source" not in idx_names:
            print("  [add ] index ix_orders_source")
            conn.execute(text(
                "CREATE INDEX ix_orders_source ON orders (source)"
            ))

        if "ix_orders_susoft_order_no" not in idx_names:
            print("  [add ] index ix_orders_susoft_order_no")
            conn.execute(text(
                "CREATE INDEX ix_orders_susoft_order_no ON orders (susoft_order_no)"
            ))

        # UNIQUE(tenant_id, susoft_uuid) — kun via constraint i Postgres.
        # I SQLite bruker vi partial unique index der susoft_uuid IS NOT NULL.
        constraints = existing_constraints(conn)
        if dialect == "postgresql":
            if "uq_order_tenant_susoft_uuid" not in constraints:
                print("  [add ] unique constraint uq_order_tenant_susoft_uuid")
                conn.execute(text(
                    "ALTER TABLE orders "
                    "ADD CONSTRAINT uq_order_tenant_susoft_uuid "
                    "UNIQUE (tenant_id, susoft_uuid)"
                ))
        else:
            if "uq_order_tenant_susoft_uuid" not in idx_names:
                print("  [add ] partial unique index uq_order_tenant_susoft_uuid")
                conn.execute(text(
                    "CREATE UNIQUE INDEX uq_order_tenant_susoft_uuid "
                    "ON orders (tenant_id, susoft_uuid) "
                    "WHERE susoft_uuid IS NOT NULL"
                ))

        print(f"Ferdig: la til {added} kolonner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

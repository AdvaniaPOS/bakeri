"""
Idempotent skjema-migrering for de nye feltene som ble lagt til i
modernisering-runden:

- customers.delivers_on_holidays (BOOLEAN, default 0)
- products.vat_class (VARCHAR, default 'food_15')
- orders.next_retry_at (DATETIME, NULL)
- orders.sync_locked_until (DATETIME, NULL)

Pluss noen nye indekser. Trygg å kjøre flere ganger.

Bruk:
    python migrate_schema.py

For SQLite. For PostgreSQL kjøres samme migreringene via SQLAlchemy reflection.
"""
import sys
from sqlalchemy import inspect, text

from app.database import engine, SessionLocal


def column_exists(conn, table: str, column: str) -> bool:
    inspector = inspect(conn)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def index_exists(conn, table: str, index_name: str) -> bool:
    inspector = inspect(conn)
    idx = [i["name"] for i in inspector.get_indexes(table)]
    return index_name in idx


def add_column_if_missing(conn, table: str, column: str, ddl: str) -> bool:
    if column_exists(conn, table, column):
        print(f"  [skip] {table}.{column} eksisterer allerede")
        return False
    print(f"  [add ] {table}.{column}")
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    return True


def create_index_if_missing(conn, table: str, index_name: str, columns: str) -> bool:
    if index_exists(conn, table, index_name):
        print(f"  [skip] index {index_name} eksisterer allerede")
        return False
    print(f"  [add ] index {index_name} ON {table}({columns})")
    conn.execute(text(f"CREATE INDEX {index_name} ON {table}({columns})"))
    return True


def main() -> int:
    print(f"Migrerer skjema mot: {engine.url}")
    with engine.begin() as conn:
        # customers
        add_column_if_missing(
            conn, "customers", "delivers_on_holidays", "BOOLEAN DEFAULT 0 NOT NULL"
        )

        # products
        add_column_if_missing(
            conn, "products", "vat_class", "VARCHAR(20) DEFAULT 'food_15' NOT NULL"
        )
        add_column_if_missing(conn, "products", "allergens", "VARCHAR(500)")

        # orders
        add_column_if_missing(conn, "orders", "next_retry_at", "DATETIME")
        add_column_if_missing(conn, "orders", "sync_locked_until", "DATETIME")
        add_column_if_missing(conn, "orders", "susoft_invoice_no", "VARCHAR(100)")
        add_column_if_missing(conn, "orders", "invoiced_at", "DATETIME")

        # tenants - SuSoft credentials per tenant
        add_column_if_missing(conn, "tenants", "susoft_login", "VARCHAR(255)")
        add_column_if_missing(conn, "tenants", "susoft_password_encrypted", "VARCHAR(500)")
        add_column_if_missing(conn, "tenants", "susoft_shop_url_key", "VARCHAR(100)")
        add_column_if_missing(conn, "tenants", "susoft_connection_status", "VARCHAR(20)")
        add_column_if_missing(conn, "tenants", "susoft_last_check_at", "DATETIME")
        add_column_if_missing(conn, "tenants", "susoft_last_error", "TEXT")
        add_column_if_missing(conn, "tenants", "last_horizon_check_at", "DATETIME")

        # indekser
        create_index_if_missing(
            conn, "orders", "ix_orders_sync_retry", "sync_status, next_retry_at"
        )
        create_index_if_missing(
            conn,
            "orders",
            "ix_orders_delivery_date_sync",
            "delivery_date, sync_status",
        )
        create_index_if_missing(
            conn,
            "customer_product_prices",
            "ix_customer_product_price_history",
            "customer_id, product_id, effective_from_date, effective_to_date",
        )

    # Lag eventuelle helt nye tabeller (f.eks. production_logs)
    print("Sjekker for nye tabeller...")
    from app.database import Base
    import app.models  # noqa: F401 -- registrer alle modeller
    import app.auth_models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    print("Ferdig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

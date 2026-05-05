"""Legg til admin-API-felt på `tenants` for SuSoft "API 2" (admin/CART-er).

Nye kolonner:
- susoft_admin_api_url               VARCHAR(500)  - default-base-url håndteres i tjenesten
- susoft_admin_login                 VARCHAR(255)
- susoft_admin_password_encrypted    VARCHAR(500)
- susoft_admin_shop_url_key          VARCHAR(100)
- susoft_admin_shop_id               INTEGER

Trygg å kjøre flere ganger. Fungerer på SQLite (dev) og PostgreSQL (prod).

Bruk:
    python migrate_susoft_admin.py
"""
from sqlalchemy import inspect, text

from app.database import engine


COLUMNS = [
    ("susoft_admin_api_url", "VARCHAR(500)"),
    ("susoft_admin_login", "VARCHAR(255)"),
    ("susoft_admin_password_encrypted", "VARCHAR(500)"),
    ("susoft_admin_shop_url_key", "VARCHAR(100)"),
    ("susoft_admin_shop_id", "INTEGER"),
]


def existing_columns(conn) -> set[str]:
    insp = inspect(conn)
    return {c["name"] for c in insp.get_columns("tenants")}


def main() -> int:
    dialect = engine.dialect.name
    print(f"Dialect: {dialect}")
    with engine.begin() as conn:
        existing = existing_columns(conn)
        added = 0
        for name, col_type in COLUMNS:
            if name in existing:
                print(f"  [skip] {name} finnes allerede")
                continue
            print(f"  [add ] {name} {col_type}")
            conn.execute(text(f"ALTER TABLE tenants ADD COLUMN {name} {col_type}"))
            added += 1
    print(f"OK ({added} kolonner lagt til)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

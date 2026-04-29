"""
Idempotent migration: ensure tenant-scoped unique indexes exist on the
running database. Safe to run repeatedly.

Why a script instead of Alembic?
- The project uses Base.metadata.create_all() which only enforces UNIQUE
  constraints on freshly-created tables. Existing SQLite/Postgres databases
  need explicit ALTER/CREATE INDEX statements.

Indexes created (each with the `WHERE is_deleted = 0` filter where applicable):

  customers     : (tenant_id, susoft_customer_id)
  products      : (tenant_id, sku)
  products      : (tenant_id, susoft_product_id)
  routes        : (tenant_id, name)
  orders        : (tenant_id, susoft_order_id)
  master_templates : (tenant_id, customer_id)  -- one active template per customer

Run:
    python migrate_unique_constraints.py
"""
from __future__ import annotations

import sys

from sqlalchemy import text

from app.database import engine

INDEXES = [
    # name, table, columns, optional WHERE clause
    ("ux_customers_tenant_susoft", "customers",
     "tenant_id, susoft_customer_id", "susoft_customer_id IS NOT NULL"),
    ("ux_products_tenant_sku", "products",
     "tenant_id, sku", "sku IS NOT NULL AND is_deleted = 0"),
    ("ux_products_tenant_susoft", "products",
     "tenant_id, susoft_product_id", "susoft_product_id IS NOT NULL"),
    ("ux_routes_tenant_name", "routes",
     "tenant_id, name", None),
    ("ux_orders_tenant_susoft", "orders",
     "tenant_id, susoft_order_id", "susoft_order_id IS NOT NULL"),
]


def main() -> int:
    dialect = engine.dialect.name
    created: list[str] = []
    skipped: list[str] = []

    with engine.begin() as conn:
        for name, table, cols, where in INDEXES:
            sql = f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({cols})"
            if where:
                # Postgres + SQLite both support partial indexes
                sql += f" WHERE {where}"
            try:
                conn.execute(text(sql))
                created.append(name)
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{name}: {e}")

    print(f"Dialect: {dialect}")
    print(f"Created/verified ({len(created)}):")
    for n in created:
        print(f"  + {n}")
    if skipped:
        print(f"Skipped ({len(skipped)}):")
        for s in skipped:
            print(f"  ! {s}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

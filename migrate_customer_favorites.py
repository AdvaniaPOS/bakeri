"""
Migrasjon: Customer favorittliste + restrict_to_favorites flag.

- Oppretter tabell `customer_favorite_products`
- Legger til `customers.restrict_to_favorites BOOLEAN NOT NULL DEFAULT false`

Idempotent - trygg å kjøre flere ganger.
"""
import sys
from sqlalchemy import inspect, text

from app.database import engine


def column_exists(conn, table: str, column: str) -> bool:
    insp = inspect(conn)
    return any(c["name"] == column for c in insp.get_columns(table))


def table_exists(conn, table: str) -> bool:
    insp = inspect(conn)
    return table in insp.get_table_names()


def main():
    dialect = engine.dialect.name
    print(f"Database dialect: {dialect}")

    with engine.begin() as conn:
        # 1) Add restrict_to_favorites column to customers
        if not column_exists(conn, "customers", "restrict_to_favorites"):
            print("Adding customers.restrict_to_favorites ...")
            if dialect == "postgresql":
                conn.execute(text(
                    "ALTER TABLE customers ADD COLUMN restrict_to_favorites BOOLEAN NOT NULL DEFAULT false"
                ))
            else:
                conn.execute(text(
                    "ALTER TABLE customers ADD COLUMN restrict_to_favorites BOOLEAN NOT NULL DEFAULT 0"
                ))
            print("  OK")
        else:
            print("customers.restrict_to_favorites already exists - skipping.")

        # 2) Create customer_favorite_products table
        if not table_exists(conn, "customer_favorite_products"):
            print("Creating table customer_favorite_products ...")
            if dialect == "postgresql":
                conn.execute(text("""
                    CREATE TABLE customer_favorite_products (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
                        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
                        CONSTRAINT uq_customer_favorite_product UNIQUE (customer_id, product_id)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_customer_favorite_products_customer_id ON customer_favorite_products(customer_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_customer_favorite_products_product_id ON customer_favorite_products(product_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_customer_favorite_products_tenant_id ON customer_favorite_products(tenant_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_customer_favorite_sort ON customer_favorite_products(customer_id, sort_order)"
                ))
            else:
                # SQLite
                conn.execute(text("""
                    CREATE TABLE customer_favorite_products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uq_customer_favorite_product UNIQUE (customer_id, product_id)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_customer_favorite_products_customer_id ON customer_favorite_products(customer_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_customer_favorite_products_product_id ON customer_favorite_products(product_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_customer_favorite_products_tenant_id ON customer_favorite_products(tenant_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_customer_favorite_sort ON customer_favorite_products(customer_id, sort_order)"
                ))
            print("  OK")
        else:
            print("Table customer_favorite_products already exists - skipping.")

    print("\nMigration completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

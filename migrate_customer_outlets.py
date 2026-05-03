"""Idempotent migrasjon: legg til Customer.parent_customer_id for utsalg / kjede-kunder."""
from sqlalchemy import text
from app.database import engine


def column_exists(conn, table: str, column: str) -> bool:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)
    rows = conn.exec_driver_sql(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{table}' AND column_name = '{column}'"
    ).fetchall()
    return len(rows) > 0


def index_exists(conn, name: str) -> bool:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        rows = conn.exec_driver_sql(
            f"SELECT name FROM sqlite_master WHERE type='index' AND name='{name}'"
        ).fetchall()
        return len(rows) > 0
    rows = conn.exec_driver_sql(
        f"SELECT indexname FROM pg_indexes WHERE indexname='{name}'"
    ).fetchall()
    return len(rows) > 0


def main():
    print("=" * 60)
    print("Migrering: Customer.parent_customer_id (utsalg / kjede)")
    print("=" * 60)

    with engine.begin() as conn:
        if not column_exists(conn, "customers", "parent_customer_id"):
            conn.execute(text(
                "ALTER TABLE customers ADD COLUMN parent_customer_id INTEGER "
                "REFERENCES customers(id) ON DELETE SET NULL"
            ))
            print("+ ALTER customers ADD COLUMN parent_customer_id")
        else:
            print("= parent_customer_id finnes allerede")

        if not index_exists(conn, "ix_customers_parent_customer_id"):
            conn.execute(text(
                "CREATE INDEX ix_customers_parent_customer_id "
                "ON customers (parent_customer_id)"
            ))
            print("+ CREATE INDEX ix_customers_parent_customer_id")
        else:
            print("= indeks ix_customers_parent_customer_id finnes")

    print("\nFerdig.")


if __name__ == "__main__":
    main()

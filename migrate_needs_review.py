"""Add needs_review/reviewed_at/reviewed_by_user_id columns to orders.

Idempotent — safe to re-run. Works for both PostgreSQL and SQLite.
"""
from __future__ import annotations

import logging
from sqlalchemy import inspect, text

from app.database import engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("migrate_needs_review")


def column_exists(conn, table: str, column: str) -> bool:
    insp = inspect(conn)
    cols = {c["name"] for c in insp.get_columns(table)}
    return column in cols


def main() -> None:
    dialect = engine.dialect.name
    log.info("Dialect: %s", dialect)

    with engine.begin() as conn:
        if not column_exists(conn, "orders", "needs_review"):
            log.info("Adding orders.needs_review")
            if dialect == "postgresql":
                conn.execute(text(
                    "ALTER TABLE orders ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT FALSE"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_orders_needs_review ON orders (needs_review)"
                ))
            else:  # sqlite
                conn.execute(text(
                    "ALTER TABLE orders ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT 0"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_orders_needs_review ON orders (needs_review)"
                ))
        else:
            log.info("orders.needs_review already exists — skipping")

        if not column_exists(conn, "orders", "reviewed_at"):
            log.info("Adding orders.reviewed_at")
            conn.execute(text("ALTER TABLE orders ADD COLUMN reviewed_at TIMESTAMP NULL"))
        else:
            log.info("orders.reviewed_at already exists — skipping")

        if not column_exists(conn, "orders", "reviewed_by_user_id"):
            log.info("Adding orders.reviewed_by_user_id")
            conn.execute(text("ALTER TABLE orders ADD COLUMN reviewed_by_user_id INTEGER NULL"))
        else:
            log.info("orders.reviewed_by_user_id already exists — skipping")

    log.info("Done.")


if __name__ == "__main__":
    main()

"""
Migrer customers.order_lead_days CHECK constraint fra (14..30) til (7..84).

SQLite støtter ikke ALTER TABLE DROP CONSTRAINT, så vi må gjøre table rebuild:
1. Rename gammel tabell
2. Opprett ny tabell med ny constraint (basert på nåværende SQLAlchemy-modeller)
3. Kopier data
4. Slett gammel tabell

For Postgres holder en enkel ALTER.

Trygg å kjøre flere ganger.

Bruk:
    python migrate_lead_days.py
"""
import sys

from sqlalchemy import inspect, text

from app.database import engine


def get_check_constraint_clause(conn) -> str | None:
    """Hent CHECK-klausulen for order_lead_days fra SQLite-skjemaet."""
    row = conn.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='customers'"
    )).fetchone()
    if not row:
        return None
    return row[0]


def migrate_sqlite() -> int:
    print("Detekterer SQLite — bruker table rebuild for CHECK-constraint.")
    with engine.begin() as conn:
        ddl = get_check_constraint_clause(conn)
        if not ddl:
            print("FEIL: customers-tabellen finnes ikke. Kjør init_db.py først.")
            return 1

        if "order_lead_days >= 7" in ddl and "order_lead_days <= 84" in ddl:
            print("[skip] CHECK-constraint er allerede 7..84.")
            return 0

        if "order_lead_days >= 14" not in ddl:
            print("[info] Fant ikke gammel constraint (14..30). Hopper over.")
            return 0

        # Slå av FK-sjekker midlertidig for å tillate rebuild med relasjoner.
        conn.execute(text("PRAGMA foreign_keys = OFF"))

        # SQLAlchemy kan opprette ny tabell via metadata, men da må vi droppe
        # den gamle først. Trygg sti: rebuild via SQL.
        # 1. Hent kolonnenavn fra inspector for å bygge SELECT.
        insp = inspect(conn)
        cols = [c["name"] for c in insp.get_columns("customers")]
        col_list = ", ".join(cols)

        # Bygg ny CREATE TABLE basert på den gamle, med oppdatert CHECK.
        new_ddl = ddl.replace(
            "order_lead_days >= 14 AND order_lead_days <= 30",
            "order_lead_days >= 7 AND order_lead_days <= 84",
        )
        # Rename target
        new_ddl = new_ddl.replace(
            'CREATE TABLE customers',
            'CREATE TABLE customers_new',
            1,
        )

        print("[1/4] Oppretter customers_new med ny CHECK-constraint")
        conn.execute(text(new_ddl))

        print(f"[2/4] Kopierer {len(cols)} kolonner")
        conn.execute(text(
            f"INSERT INTO customers_new ({col_list}) SELECT {col_list} FROM customers"
        ))

        print("[3/4] Sletter gammel customers-tabell")
        conn.execute(text("DROP TABLE customers"))

        print("[4/4] Renamer customers_new -> customers")
        conn.execute(text("ALTER TABLE customers_new RENAME TO customers"))

        # Indekser må opprettes på nytt — SQLAlchemy-metadata vet om dem.
        # Enklest: importer modeller og la SQLAlchemy opprette manglende indekser.
        from app.models import Customer  # noqa: F401
        from app.database import Base
        Base.metadata.create_all(conn, checkfirst=True)

        conn.execute(text("PRAGMA foreign_keys = ON"))

    print("Ferdig: customers.order_lead_days støtter nå 7..84 dager (1..12 uker).")
    return 0


def migrate_postgres() -> int:
    print("Detekterer PostgreSQL — bruker ALTER TABLE.")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE customers DROP CONSTRAINT IF EXISTS check_order_lead_days_range"
        ))
        conn.execute(text(
            "ALTER TABLE customers ADD CONSTRAINT check_order_lead_days_range "
            "CHECK (order_lead_days >= 7 AND order_lead_days <= 84)"
        ))
    print("Ferdig: customers.order_lead_days støtter nå 7..84 dager (1..12 uker).")
    return 0


def main() -> int:
    print(f"Migrerer mot: {engine.url}")
    if engine.url.get_backend_name() == "sqlite":
        return migrate_sqlite()
    return migrate_postgres()


if __name__ == "__main__":
    sys.exit(main())

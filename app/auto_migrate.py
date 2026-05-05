"""
Idempotent skjema-synkronisering ved app-oppstart.

Bakgrunn
--------
Vi har fram til nå manglet en migrasjons-disiplin (Alembic), og hver gang
det legges til en ny kolonne i `app/models.py` har vi måttet kjøre
ad-hoc `ALTER TABLE`-skript på server. Det har resultert i 500-feil i
prod når noen glemte å migrere før restart.

Denne modulen kjøres automatisk fra `app.main.lifespan` ved oppstart og:

1. Lager alle manglende tabeller (`Base.metadata.create_all`).
2. Sammenligner SQLAlchemy-modellen med faktisk DB og legger til
   manglende kolonner med `ALTER TABLE ... ADD COLUMN`.
3. Backfiller fornuftige defaults så NOT-NULL-kolonner ikke knekker
   Pydantic-validering.
4. Logger hva som ble gjort.

Begrensninger
-------------
- Endringer i kolonne-typer/navnebytter/sletting håndteres ikke (bevisst
  konservativt — slikt skal gjøres manuelt eller via Alembic).
- Foreign-key-constraints på nye kolonner legges ikke til på SQLite
  (SQLite støtter ikke `ADD CONSTRAINT`). Det aksepterer vi siden vi
  uansett bytter til Postgres for prod.

Bruk
----
Kjøres automatisk ved oppstart. Kan også kjøres manuelt:

    python -m app.auto_migrate
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# Backfill-defaults for kolonner som er NOT NULL i modellen, men der
# eksisterende rader får NULL når kolonnen legges til. Pydantic-validering
# krasjer hvis disse er None.
#
# Format: {(table_name, column_name): default_value}
_BACKFILL_DEFAULTS: dict[tuple[str, str], Any] = {
    ("products", "batch_size"): 1,
    ("products", "production_lead_minutes"): 0,
    ("products", "production_days"): 0,
    ("products", "is_active_overridden"): False,
    ("order_lines", "delivered_quantity"): 0,
    ("order_lines", "waste_quantity"): 0,
    ("order_lines", "return_quantity"): 0,
    ("tenants", "susoft_config_locked"): False,
}


# Partial unique indexes som skal opprettes idempotent.
# Format: index_name -> (table, sql_snippet_uten_create_index)
#
# MERK: Hvis det finnes duplikat-rader i tabellen ved oppstart vil
# CREATE UNIQUE INDEX feile — da logges det og indeksen hoppes over slik
# at appen fortsatt kan starte. Rydding må da gjøres manuelt.
_PARTIAL_UNIQUE_INDEXES: dict[str, tuple[str, str]] = {
    # Hindrer at to mal-genererte ordrer opprettes for samme
    # (tenant, customer, delivery_date) ved race-conditions.
    "uq_orders_template_customer_date": (
        "orders",
        "(tenant_id, customer_id, delivery_date) "
        "WHERE is_deleted = false AND generated_from_template_id IS NOT NULL",
    ),
}


def _column_ddl(column, dialect) -> str:
    """Bygg DDL-fragment for en SQLAlchemy-kolonne (uten constraints)."""
    col_type = column.type.compile(dialect=dialect)
    parts = [column.name, col_type]

    # NOT NULL kun hvis kolonnen har en default (ellers feiler ALTER TABLE
    # på rader som finnes fra før).
    has_default = column.server_default is not None or (
        column.default is not None and getattr(column.default, "is_scalar", False)
    )
    if not column.nullable and has_default:
        parts.append("NOT NULL")

    if column.server_default is not None:
        parts.append(f"DEFAULT {column.server_default.arg}")
    elif column.default is not None and getattr(column.default, "is_scalar", False):
        v = column.default.arg
        if isinstance(v, bool):
            v = 1 if v else 0
        elif isinstance(v, str):
            v = repr(v)
        parts.append(f"DEFAULT {v}")

    return " ".join(parts)


def sync_schema(engine: Engine) -> dict[str, list[str]]:
    """
    Synkroniser DB-skjema med SQLAlchemy-modellene.

    Returnerer dict med to lister:
        - "added":   ["table.col", ...]
        - "skipped": ["table.col: reason", ...]
    """
    # Importer alle modeller så Base.metadata er fullstendig.
    from app.database import Base  # noqa: PLC0415
    import app.models  # noqa: F401, PLC0415
    import app.auth_models  # noqa: F401, PLC0415

    added: list[str] = []
    skipped: list[str] = []
    backfilled: list[str] = []

    with engine.begin() as conn:
        # 1. Lag tabeller som ikke finnes.
        Base.metadata.create_all(bind=conn)

        # 2. Diff kolonner.
        insp = inspect(conn)
        existing_tables = set(insp.get_table_names())

        for table_name, table in Base.metadata.tables.items():
            if table_name not in existing_tables:
                # create_all over skulle ha laget den, men hvis ikke — hopp.
                continue

            existing_cols = {c["name"] for c in insp.get_columns(table_name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                ddl = f"ALTER TABLE {table_name} ADD COLUMN {_column_ddl(col, engine.dialect)}"
                try:
                    conn.execute(text(ddl))
                    added.append(f"{table_name}.{col.name}")
                    logger.info("auto_migrate: added column %s.%s", table_name, col.name)
                except Exception as exc:  # noqa: BLE001
                    skipped.append(f"{table_name}.{col.name}: {exc}")
                    logger.warning("auto_migrate: kunne ikke legge til %s.%s: %s",
                                   table_name, col.name, exc)

        # 3. Backfill defaults der vi vet om dem (idempotent — bare WHERE col IS NULL).
        existing_tables_after = set(inspect(conn).get_table_names())
        for (tn, cn), default in _BACKFILL_DEFAULTS.items():
            if tn not in existing_tables_after:
                continue
            existing_cols = {c["name"] for c in inspect(conn).get_columns(tn)}
            if cn not in existing_cols:
                continue
            try:
                if isinstance(default, bool):
                    val = 1 if default else 0
                else:
                    val = default
                result = conn.execute(
                    text(f"UPDATE {tn} SET {cn} = :v WHERE {cn} IS NULL"),
                    {"v": val},
                )
                if result.rowcount:
                    backfilled.append(f"{tn}.{cn}={default} ({result.rowcount} rader)")
                    logger.info("auto_migrate: backfilled %s.%s=%s for %d rader",
                                tn, cn, default, result.rowcount)
            except Exception as exc:  # noqa: BLE001
                skipped.append(f"backfill {tn}.{cn}: {exc}")

        # 4. Partial unique indexes (race-condition-vern). Idempotent via
        #    IF NOT EXISTS — feil ved eksisterende dup-rader logges og
        #    hoppes over slik at oppstart ikke knekker.
        dialect_name = engine.dialect.name
        if dialect_name in ("postgresql", "sqlite"):
            existing_tables_after = set(inspect(conn).get_table_names())
            for idx_name, (table, snippet) in _PARTIAL_UNIQUE_INDEXES.items():
                if table not in existing_tables_after:
                    continue
                ddl = f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} ON {table} {snippet}"
                try:
                    conn.execute(text(ddl))
                    logger.info("auto_migrate: ensured unique index %s", idx_name)
                except Exception as exc:  # noqa: BLE001
                    skipped.append(f"index {idx_name}: {exc}")
                    logger.warning(
                        "auto_migrate: kunne ikke opprette unique index %s "
                        "(sannsynligvis pga eksisterende dup-rader): %s",
                        idx_name, exc,
                    )

    return {"added": added, "skipped": skipped, "backfilled": backfilled}


def main() -> int:
    """CLI-inngang for manuell kjøring."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from app.database import engine
    result = sync_schema(engine)
    print("=" * 60)
    print(f"Lagt til: {len(result['added'])}")
    for a in result["added"]:
        print(f"  + {a}")
    print(f"Backfilled: {len(result['backfilled'])}")
    for b in result["backfilled"]:
        print(f"  ~ {b}")
    print(f"Hoppet over: {len(result['skipped'])}")
    for s in result["skipped"]:
        print(f"  - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

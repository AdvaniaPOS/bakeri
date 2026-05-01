#!/usr/bin/env python3
"""
Migrer data fra SQLite til Postgres.

Bruk
----
1. Sett opp Postgres-database og bruker:

       sudo -u postgres psql
       CREATE USER bakeri WITH PASSWORD 'bytt-meg';
       CREATE DATABASE bakeri OWNER bakeri;
       GRANT ALL PRIVILEGES ON DATABASE bakeri TO bakeri;
       \q

2. Kjør migreringen (les fra SQLite, skriv til Postgres):

       export SOURCE_URL=sqlite:///./lampeland_bakeri.db
       export DEST_URL=postgresql+psycopg2://bakeri:bytt-meg@localhost/bakeri
       python scripts/migrate_sqlite_to_postgres.py

3. Oppdater .env til å bruke Postgres:

       DATABASE_URL=postgresql+psycopg2://bakeri:bytt-meg@localhost/bakeri

4. Restart backend.

Sikkerhet
---------
- Skriptet wiper destinasjonen (TRUNCATE) før import, men spør først.
- Tar backup av SQLite-fil med tidsstempel før noe gjøres.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

# Sørg for at vi kan importere `app` selv om vi kjøres direkte.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import Base  # noqa: E402
import app.models  # noqa: F401, E402
import app.auth_models  # noqa: F401, E402


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [skriv 'JA' for å fortsette]: ").strip()
    return answer == "JA"


def main() -> int:
    src_url = os.getenv("SOURCE_URL", "sqlite:///./lampeland_bakeri.db")
    dst_url = os.getenv("DEST_URL")
    if not dst_url:
        print("FEIL: sett DEST_URL miljøvariabel til Postgres-URL.", file=sys.stderr)
        return 2

    print(f"Kilde: {src_url}")
    print(f"Mål  : {dst_url}")
    print()

    # 1. Ta backup av SQLite om det er fil-basert.
    if src_url.startswith("sqlite:///"):
        path = Path(src_url.replace("sqlite:///", ""))
        if path.exists():
            backup = path.with_suffix(f".pre-pg-migrate-{datetime.now():%Y%m%d-%H%M%S}.db")
            shutil.copy2(path, backup)
            print(f"Backup av SQLite: {backup}")

    src = create_engine(src_url)
    dst = create_engine(dst_url)

    # 2. Lag skjema i destinasjonen.
    print("Lager skjema i Postgres ...")
    Base.metadata.create_all(bind=dst)

    # 3. Bekreft sletting.
    if not confirm("Dette TRUNCATER alle tabeller i destinasjonen før import."):
        print("Avbrutt.")
        return 1

    # 4. Truncate i riktig rekkefølge (Postgres-only, CASCADE for å takle FK).
    insp_dst = inspect(dst)
    dst_tables = insp_dst.get_table_names()
    print(f"Truncater {len(dst_tables)} tabeller ...")
    with dst.begin() as conn:
        for tn in dst_tables:
            conn.execute(text(f'TRUNCATE TABLE "{tn}" RESTART IDENTITY CASCADE'))

    # 5. Kopier rad for rad. Bruker reflection så vi støtter at kilde-skjemaet
    #    har færre kolonner enn modellen (etter at vi har auto-migrert kun
    #    Postgres senere).
    insp_src = inspect(src)
    src_tables = insp_src.get_table_names()
    SrcSession = sessionmaker(bind=src)
    DstSession = sessionmaker(bind=dst)

    src_session = SrcSession()
    dst_session = DstSession()
    try:
        # Kopier i samme rekkefølge som SQLAlchemy-metadata oppgir
        # (foreldre før barn).
        ordered = [t.name for t in Base.metadata.sorted_tables if t.name in src_tables]
        for tn in ordered:
            src_cols = [c["name"] for c in insp_src.get_columns(tn)]
            dst_cols = [c["name"] for c in insp_dst.get_columns(tn)]
            common = [c for c in src_cols if c in dst_cols]

            rows = src_session.execute(text(f'SELECT * FROM {tn}')).mappings().all()
            if not rows:
                print(f"  - {tn}: 0 rader")
                continue

            quoted_cols = ', '.join(f'"{c}"' for c in common)
            placeholders = ', '.join(f":{c}" for c in common)
            insert_sql = text(
                f'INSERT INTO "{tn}" ({quoted_cols}) VALUES ({placeholders})'
            )
            payloads = [{c: r[c] for c in common} for r in rows]
            dst_session.execute(insert_sql, payloads)
            print(f"  + {tn}: {len(rows)} rader")

        dst_session.commit()

        # 6. Oppdater Postgres-sekvenser så autoincrement fortsetter riktig.
        print("Justerer sekvenser ...")
        with dst.begin() as conn:
            for tn in ordered:
                cols = insp_dst.get_columns(tn)
                pks = [c for c in cols if c.get("autoincrement") and c.get("primary_key")]
                # Fallback: bare id-kolonner.
                if not pks:
                    pks = [c for c in cols if c["name"] == "id"]
                for pk in pks:
                    cn = pk["name"]
                    seq_name = f'{tn}_{cn}_seq'
                    try:
                        conn.execute(text(
                            f"SELECT setval('{seq_name}', "
                            f"COALESCE((SELECT MAX({cn}) FROM \"{tn}\"), 1), true)"
                        ))
                    except Exception as exc:
                        print(f"  skip seq {seq_name}: {exc}")

        print("\nFerdig. Oppdater DATABASE_URL i .env og restart backend.")
        return 0
    finally:
        src_session.close()
        dst_session.close()


if __name__ == "__main__":
    raise SystemExit(main())

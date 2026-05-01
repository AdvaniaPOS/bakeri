"""
TOM HELE DATABASEN.

ADVARSEL: Sletter ALT - alle tabeller, alle data, alle tenants/brukere.
Kjor denne kun for full restart av testmiljo.

Etter wipe: kjor scripts/create_user.py for aa lage en ny SUPER_ADMIN bruker.

Bruk:
    python wipe_database.py --confirm WIPE
"""
import argparse
import sys

from sqlalchemy import text

from app.database import engine, Base
# Importer alle modeller saa metadata kjenner alle tabellene
from app import auth_models, models  # noqa: F401


def main():
    parser = argparse.ArgumentParser(description="Wipe all tables in the database")
    parser.add_argument(
        "--confirm",
        required=True,
        help="Maa vaere 'WIPE' for aa kjore",
    )
    args = parser.parse_args()

    if args.confirm != "WIPE":
        print("Feil: --confirm maa vaere 'WIPE'", file=sys.stderr)
        sys.exit(1)

    print(f"Database: {engine.url}")
    answer = input("Er du HELT sikker? Skriv 'JA' for aa fortsette: ")
    if answer != "JA":
        print("Avbrutt.")
        sys.exit(0)

    print("Dropper alle tabeller...")
    with engine.begin() as conn:
        # Postgres: drop hele schema for aa unngaa FK-floker
        if engine.url.get_backend_name() == "postgresql":
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        else:
            Base.metadata.drop_all(bind=conn)

    print("Oppretter alle tabeller paa nytt...")
    Base.metadata.create_all(bind=engine)

    print("\nFerdig. Databasen er tom.")
    print("Neste steg:")
    print("  1) python scripts/create_user.py   # opprett super-admin")
    print("  2) Logg inn og opprett tenants i Master-portalen")


if __name__ == "__main__":
    main()

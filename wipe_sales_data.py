"""
Tom databasen for ALL salgs- og tenant-data, men behold SUPER_ADMIN-brukere.

Etter wipe:
  - Alle tenants, customers, products, orders, ruter, maler, faktura-spor osv.
    er borte.
  - SUPER_ADMIN-brukere er beholdt (med samme passord, 2FA, e-post).
  - Du kan logge inn som superadmin og opprette nytt firma (tenant) fra
    Master-portalen.

Bruk:
    python wipe_sales_data.py --confirm WIPE
"""
import argparse
import os
import sys

from sqlalchemy import text

from app.database import engine, Base, SessionLocal
# Importer alle modeller saa Base.metadata kjenner alle tabellene
from app import auth_models, models  # noqa: F401
from app.auth_models import User, UserRole


def _guard_production_wipe() -> None:
    app_env = (os.getenv("APP_ENV") or "").strip().lower()
    if app_env in {"production", "prod", "staging"} and os.getenv("ALLOW_PROD_WIPE") != "YES_I_UNDERSTAND":
        print(
            "Refuserer aa wipe salgsdata i production-liknende miljo. "
            "Sett ALLOW_PROD_WIPE=YES_I_UNDERSTAND hvis dette er bevisst.",
            file=sys.stderr,
        )
        sys.exit(2)


def main():
    _guard_production_wipe()

    parser = argparse.ArgumentParser(
        description="Wipe all sales/tenant data, keep SUPER_ADMIN users"
    )
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

    # Steg 1: hent ut alle SUPER_ADMIN-brukere foer wipe
    db = SessionLocal()
    try:
        super_admins = (
            db.query(User)
            .filter(User.role == UserRole.SUPER_ADMIN)
            .all()
        )
        if not super_admins:
            print("ADVARSEL: Ingen SUPER_ADMIN funnet. Etter wipe maa du kjore "
                  "scripts/create_user.py for aa lage en ny.")
        else:
            print(f"Fant {len(super_admins)} SUPER_ADMIN-bruker(e):")
            for u in super_admins:
                print(f"  - {u.email} ({u.first_name} {u.last_name})")

        # Snapshot av alle felt vi vil restore
        snapshot = []
        for u in super_admins:
            snapshot.append({
                "email": u.email,
                "password_hash": u.password_hash,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone,
                "avatar_url": u.avatar_url,
                "is_active": u.is_active,
                "email_verified": u.email_verified,
                "totp_secret": u.totp_secret,
                "totp_enabled": u.totp_enabled,
                "preferences": u.preferences,
            })
    finally:
        db.close()

    answer = input("\nDette sletter ALLE tenants, kunder, produkter, ordrer, "
                   "fakturaer, ruter, maler m.m.\nSkriv 'JA' for aa fortsette: ")
    if answer != "JA":
        print("Avbrutt.")
        sys.exit(0)

    # Steg 2: drop + create
    print("\nDropper alle tabeller...")
    with engine.begin() as conn:
        if engine.url.get_backend_name() == "postgresql":
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        else:
            Base.metadata.drop_all(bind=conn)

    print("Oppretter alle tabeller paa nytt...")
    Base.metadata.create_all(bind=engine)

    # Steg 3: re-insert SUPER_ADMIN-brukerne
    if snapshot:
        print(f"\nGjenoppretter {len(snapshot)} SUPER_ADMIN-bruker(e)...")
        db = SessionLocal()
        try:
            for s in snapshot:
                u = User(
                    tenant_id=None,  # super_admin har ikke tenant
                    email=s["email"],
                    password_hash=s["password_hash"],
                    first_name=s["first_name"],
                    last_name=s["last_name"],
                    phone=s["phone"],
                    avatar_url=s["avatar_url"],
                    role=UserRole.SUPER_ADMIN,
                    is_active=s["is_active"],
                    email_verified=s["email_verified"],
                    totp_secret=s["totp_secret"],
                    totp_enabled=s["totp_enabled"],
                    preferences=s["preferences"],
                )
                db.add(u)
            db.commit()
            print("Gjenoppretting OK.")
        finally:
            db.close()

    print("\nFerdig. Databasen er tom for salgsdata, SUPER_ADMIN beholdt.")
    print("Logg inn som superadmin og opprett tenants i Master-portalen.")


if __name__ == "__main__":
    main()

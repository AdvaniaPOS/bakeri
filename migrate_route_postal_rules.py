"""
Migration: legg til tabellen route_postal_rules.
Kjor: python migrate_route_postal_rules.py
"""
from app.database import engine
from app.models import Base, RoutePostalRule


def main():
    print("Oppretter route_postal_rules-tabellen ...")
    RoutePostalRule.__table__.create(bind=engine, checkfirst=True)
    print("Ferdig.")


if __name__ == "__main__":
    main()

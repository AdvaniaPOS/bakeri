#!/usr/bin/env python3
"""
Importer kunder og produkter fra JSON-filer inn i databasen.

Erstatter de tidligere skriptene:
    - import_susoft_customers.py
    - import_susoft_products.py
    - import_to_db.py

ORM-basert (ikke raw SQL), idempotent (oppdaterer hvis eksisterer),
og krever --tenant-slug for å sikre tenant-scope.

Eksempler
---------
    # Kunder fra SuSoft
    python -m scripts.import_data customers --tenant-slug jonb

    # Produkter fra SuSoft
    python -m scripts.import_data products --tenant-slug jonb --source susoft

    # Egne bakeri-produkter
    python -m scripts.import_data products --tenant-slug jonb --source bakery

    # Tøm tenantens rader først
    python -m scripts.import_data customers --tenant-slug jonb --wipe
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()

from app.database import SessionLocal
from app.auth_models import Tenant
from app.models import Customer, Product

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CUSTOMER_FILES = [
    DATA_DIR / "susoft_customers.json",
    DATA_DIR / "susoft_customers_full.json",
]

PRODUCT_SOURCES = {
    "susoft": DATA_DIR / "susoft_products.json",
    "bakery": DATA_DIR / "bakeri_produkter.json",
}


def _safe_decimal(value, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value is not None else default))
    except (InvalidOperation, TypeError):
        return Decimal(default)


def _load_first_existing(paths: Iterable[Path]) -> tuple[list, Path]:
    for p in paths:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f), p
    raise FileNotFoundError(f"Ingen av filene finnes: {[str(p) for p in paths]}")


def _resolve_tenant(db, slug: str) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if not tenant:
        raise SystemExit(f"❌ Tenant '{slug}' finnes ikke. Opprett først via scripts.create_user.")
    return tenant


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def _customer_name(c: dict) -> str:
    first = (c.get("firstName") or "").strip()
    last = (c.get("lastName") or "").strip()
    display = (c.get("displayName") or "").strip()
    if display:
        return display[:255]
    full = f"{first} {last}".strip()
    return (full or f"Kunde #{c.get('id')}")[:255]


def import_customers(*, tenant_slug: str, wipe: bool = False) -> int:
    customers_data, source = _load_first_existing(CUSTOMER_FILES)
    print(f"📥 Lastet {len(customers_data)} kunder fra {source.name}")

    db = SessionLocal()
    try:
        tenant = _resolve_tenant(db, tenant_slug)

        if wipe:
            n = db.query(Customer).filter(Customer.tenant_id == tenant.id).delete()
            db.commit()
            print(f"🧹 Slettet {n} eksisterende kunder for tenant {tenant_slug}")

        seen: set[str] = set()
        created = updated = skipped = 0

        for c in customers_data:
            susoft_id = str(c.get("id") or "").strip()
            if not susoft_id or susoft_id in seen:
                skipped += 1
                continue
            seen.add(susoft_id)

            addr = c.get("address") or {}
            phone = addr.get("mobilePhone") or addr.get("landLinePhone")
            street = addr.get("addressLine1") or addr.get("addressLine2")

            existing = (
                db.query(Customer)
                .filter(
                    Customer.tenant_id == tenant.id,
                    Customer.susoft_customer_id == susoft_id,
                )
                .first()
            )
            if existing:
                existing.name = _customer_name(c)
                existing.email = (addr.get("email") or "")[:254] or None
                existing.phone = (phone or "")[:50] or None
                existing.street_address = (street or "")[:500] or None
                existing.city = (addr.get("city") or "")[:100] or None
                existing.postal_code = (addr.get("zipCode") or "")[:20] or None
                existing.is_active = bool(c.get("isActive", True))
                updated += 1
            else:
                db.add(Customer(
                    tenant_id=tenant.id,
                    susoft_customer_id=susoft_id,
                    name=_customer_name(c),
                    email=(addr.get("email") or "")[:254] or None,
                    phone=(phone or "")[:50] or None,
                    street_address=(street or "")[:500] or None,
                    city=(addr.get("city") or "")[:100] or None,
                    postal_code=(addr.get("zipCode") or "")[:20] or None,
                    country="Norway",
                    is_active=bool(c.get("isActive", True)),
                ))
                created += 1

            if (created + updated) % 200 == 0:
                db.commit()

        db.commit()
        print(f"✅ Kunder: opprettet={created}, oppdatert={updated}, hoppet over={skipped}")
        return created + updated
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

def _build_product_kwargs(p: dict, *, source: str) -> dict | None:
    """Map et JSON-objekt til Product-felter. Returnerer None hvis ugyldig."""
    if source == "susoft":
        susoft_id = p.get("id")
        if not susoft_id:
            return None
        sku = p.get("externalRefId") or p.get("barcode") or str(susoft_id)
        return dict(
            susoft_product_id=str(susoft_id),
            sku=str(sku)[:100],
            name=(p.get("name") or f"Produkt {susoft_id}")[:255],
            description=p.get("description"),
            category=p.get("categoryName") or p.get("category1"),
            default_price=_safe_decimal(p.get("retailPrice")),
            unit=(p.get("unit") or "stk")[:20],
            vat_rate=_safe_decimal(p.get("vatPercent"), default="15"),
            is_active=bool(p.get("active", True)),
        )

    # bakery (data/bakeri_produkter.json)
    sku = p.get("id")
    if not sku:
        return None
    return dict(
        susoft_product_id=str(sku),
        sku=str(sku)[:100],
        name=(p.get("name") or "")[:255],
        description=(p.get("description") or None),
        category=(p.get("category") or None),
        default_price=_safe_decimal(p.get("retailPrice") or p.get("price")),
        unit=(p.get("unit") or "stk")[:20],
        vat_rate=_safe_decimal(p.get("vatPercent") or p.get("vat_rate"), default="15"),
        is_active=bool(p.get("active", True)),
    )


def import_products(*, tenant_slug: str, source: str, wipe: bool = False) -> int:
    if source not in PRODUCT_SOURCES:
        raise SystemExit(f"❌ Ukjent --source '{source}'. Velg: {list(PRODUCT_SOURCES)}")
    path = PRODUCT_SOURCES[source]
    if not path.exists():
        raise SystemExit(f"❌ Fant ikke {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"📥 Lastet {len(data)} produkter fra {path.name}")

    db = SessionLocal()
    try:
        tenant = _resolve_tenant(db, tenant_slug)

        if wipe:
            n = db.query(Product).filter(Product.tenant_id == tenant.id).delete()
            db.commit()
            print(f"🧹 Slettet {n} eksisterende produkter for tenant {tenant_slug}")

        seen: set[str] = set()
        created = updated = skipped = 0

        for p in data:
            kwargs = _build_product_kwargs(p, source=source)
            if kwargs is None:
                skipped += 1
                continue
            susoft_id = kwargs["susoft_product_id"]
            if susoft_id in seen:
                skipped += 1
                continue
            seen.add(susoft_id)

            existing = (
                db.query(Product)
                .filter(
                    Product.tenant_id == tenant.id,
                    Product.susoft_product_id == susoft_id,
                )
                .first()
            )
            if existing:
                for k, v in kwargs.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(Product(tenant_id=tenant.id, **kwargs))
                created += 1

            if (created + updated) % 200 == 0:
                db.commit()

        db.commit()
        print(f"✅ Produkter: opprettet={created}, oppdatert={updated}, hoppet over={skipped}")
        return created + updated
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importer kunder/produkter til databasen.")
    sub = parser.add_subparsers(dest="kind", required=True)

    p_cust = sub.add_parser("customers", help="Importer kunder fra SuSoft JSON.")
    p_cust.add_argument("--tenant-slug", required=True)
    p_cust.add_argument("--wipe", action="store_true", help="Slett eksisterende kunder for tenant først.")

    p_prod = sub.add_parser("products", help="Importer produkter.")
    p_prod.add_argument("--tenant-slug", required=True)
    p_prod.add_argument("--source", choices=list(PRODUCT_SOURCES), default="susoft")
    p_prod.add_argument("--wipe", action="store_true", help="Slett eksisterende produkter for tenant først.")

    args = parser.parse_args(argv)

    if args.kind == "customers":
        import_customers(tenant_slug=args.tenant_slug, wipe=args.wipe)
    elif args.kind == "products":
        import_products(tenant_slug=args.tenant_slug, source=args.source, wipe=args.wipe)
    return 0


if __name__ == "__main__":
    sys.exit(main())

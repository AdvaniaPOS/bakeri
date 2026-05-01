#!/usr/bin/env python3
"""
Opprett (eller oppdater) en bruker og tilhørende tenant.

Erstatter de tidligere skriptene `add_demo_user.py` og `create_user.py`.
Idempotent: Trygg å kjøre flere ganger.

Eksempler
---------
    # Demo-bruker (demo@bakeri.local / demo123, tenant=demo)
    python -m scripts.create_user --demo

    # Egendefinert bruker
    python -m scripts.create_user \
        --email jon@easify.no --password "hemmelig" \
        --first-name Jon --last-name Bakeri \
        --tenant-slug jonb --tenant-name "Lampeland Bakeri"
"""
from __future__ import annotations

import argparse
import getpass
import sys

import bcrypt
from dotenv import load_dotenv

load_dotenv()

from app.database import SessionLocal
from app.auth_models import (
    SubscriptionPlan,
    SubscriptionStatus,
    Tenant,
    User,
    UserRole,
)


def _hash_password(password: str, *, fast: bool = False) -> str:
    """Hash password med bcrypt. `fast=True` brukes kun for demo-bruker."""
    rounds = 4 if fast else 12
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def upsert_tenant_and_user(
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    tenant_slug: str,
    tenant_name: str,
    role: UserRole = UserRole.TENANT_ADMIN,
    fast_hash: bool = False,
) -> tuple[int, int]:
    """
    Sikre at tenant og bruker eksisterer. Returnerer (tenant_id, user_id).

    - Tenant opprettes hvis slug ikke finnes (FREE_TRIAL/ACTIVE).
    - Bruker opprettes hvis e-post ikke finnes; ellers oppdateres passord/navn/rolle.
    """
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
        if not tenant:
            tenant = Tenant(
                name=tenant_name,
                slug=tenant_slug,
                email=email,
                country="NO",
                subscription_plan=SubscriptionPlan.FREE_TRIAL,
                subscription_status=SubscriptionStatus.ACTIVE,
                is_active=True,
            )
            db.add(tenant)
            db.flush()
            print(f"✅ Opprettet tenant '{tenant_slug}' (id={tenant.id})")
        else:
            print(f"⏭️  Tenant '{tenant_slug}' finnes (id={tenant.id})")

        password_hash = _hash_password(password, fast=fast_hash)

        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                password_hash=password_hash,
                first_name=first_name,
                last_name=last_name,
                tenant_id=tenant.id,
                role=role,
                is_active=True,
                email_verified=True,
            )
            db.add(user)
            db.commit()
            print(f"✅ Opprettet bruker '{email}' (id={user.id})")
        else:
            user.password_hash = password_hash
            user.first_name = first_name
            user.last_name = last_name
            user.tenant_id = tenant.id
            user.role = role
            user.is_active = True
            user.email_verified = True
            db.commit()
            print(f"♻️  Oppdaterte bruker '{email}' (id={user.id})")

        return tenant.id, user.id
    except Exception as exc:
        db.rollback()
        print(f"❌ Feil: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opprett eller oppdater bruker + tenant.")
    parser.add_argument("--demo", action="store_true", help="Opprett demo-bruker (demo@bakeri.local / demo123).")
    parser.add_argument(
        "--super-admin",
        action="store_true",
        help="Opprett super-admin-bruker (krever --email + --password). Bruker 'platform'-tenant.",
    )
    parser.add_argument("--email")
    parser.add_argument("--password", help="Hvis utelatt og ikke --demo, blir du spurt interaktivt.")
    parser.add_argument("--first-name", default="")
    parser.add_argument("--last-name", default="")
    parser.add_argument("--tenant-slug")
    parser.add_argument("--tenant-name")
    parser.add_argument(
        "--role",
        choices=[r.value for r in UserRole],
        default=UserRole.TENANT_ADMIN.value,
        help="Brukerrolle (default: tenant_admin).",
    )

    args = parser.parse_args(argv)

    if args.demo:
        upsert_tenant_and_user(
            email="demo@bakeri.local",
            password="demo123",
            first_name="Demo",
            last_name="Bruker",
            tenant_slug="demo",
            tenant_name="Demo Bakeri",
            fast_hash=True,
        )
        print("\n✅ Demo-oppsett komplett (innlogging: demo@bakeri.local / demo123)")
        return 0

    if args.super_admin:
        if not args.email:
            parser.error("--super-admin krever --email")
        password = args.password or getpass.getpass("Passord: ")
        if not password:
            parser.error("Passord kan ikke være tomt.")
        upsert_tenant_and_user(
            email=args.email,
            password=password,
            first_name=args.first_name or "Super",
            last_name=args.last_name or "Admin",
            tenant_slug="platform",
            tenant_name="Platform Admin",
            role=UserRole.SUPER_ADMIN,
        )
        print(f"\n✅ Super-admin opprettet ({args.email}). Logg inn og gå til /tenants-admin.")
        return 0

    missing = [f for f in ("email", "tenant_slug", "tenant_name") if not getattr(args, f.replace("-", "_"))]
    if missing:
        parser.error(f"Mangler påkrevde argumenter: {', '.join('--' + m for m in missing)}")

    password = args.password or getpass.getpass("Passord: ")
    if not password:
        parser.error("Passord kan ikke være tomt.")

    upsert_tenant_and_user(
        email=args.email,
        password=password,
        first_name=args.first_name,
        last_name=args.last_name,
        tenant_slug=args.tenant_slug,
        tenant_name=args.tenant_name,
        role=UserRole(args.role),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

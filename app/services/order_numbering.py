"""
Allokering og formatering av per-tenant ordrenr.

Ordrenr-format: {PREFIX}-{YEAR}-{SEQ:06d}
Eksempel: LAM-2026-000123 for tenant slug "lampeland-bakeri", levering 2026.

Sekvensen er per tenant, monotont okende. Aar er hentet fra delivery_date.
"""
from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth_models import Tenant
from app.models import Order


def tenant_order_prefix(slug: str | None) -> str:
    """Tre-bokstav prefiks fra tenant-slug, store bokstaver."""
    cleaned = "".join(c for c in (slug or "") if c.isalnum()).upper()
    return (cleaned[:3] or "ORD").ljust(3, "X")


def format_order_no(prefix: str, year: int, seq: int) -> str:
    return f"{prefix}-{year}-{seq:06d}"


def allocate_order_no(db: Session, tenant: Tenant, order: Order) -> None:
    """
    Allokerer order_no_seq + order_no_display paa en (uflushet eller flushet) Order.

    Kalles foer eller etter db.add(order) men foer commit. Krever
    delivery_date paa orderen for aa bestemme aar.
    """
    if order.order_no_seq is not None:
        return  # allerede satt
    next_seq = (
        db.execute(
            select(func.coalesce(func.max(Order.order_no_seq), 0))
            .where(Order.tenant_id == tenant.id)
        ).scalar_one()
    ) + 1
    year = order.delivery_date.year if order.delivery_date else date_type.today().year
    prefix = tenant_order_prefix(tenant.slug)
    order.order_no_seq = next_seq
    order.order_no_display = format_order_no(prefix, year, next_seq)

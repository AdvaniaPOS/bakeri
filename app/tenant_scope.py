"""
Tenant-scoping helpers for API endpoints.

Provides a single source of truth for filtering queries and validating
ownership of database rows by the currently authenticated tenant.
"""
from datetime import datetime
from typing import Optional, TypeVar, Type

from fastapi import HTTPException, status
from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

T = TypeVar("T")


def scope(query: Select, model, tenant_id: int) -> Select:
    """Add tenant_id filter to a Select query if the model is tenant-scoped."""
    if hasattr(model, "tenant_id"):
        return query.where(model.tenant_id == tenant_id)
    return query


def get_or_404(db: Session, model: Type[T], obj_id, tenant_id: int,
                detail: str = "Not found") -> T:
    """Fetch an object by id; 404 if missing OR belongs to another tenant.

    Also enforces is_deleted=False for soft-delete models.
    """
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    if hasattr(obj, "tenant_id") and obj.tenant_id != tenant_id:
        # Pretend it doesn't exist (don't leak existence across tenants)
        raise HTTPException(status_code=404, detail=detail)
    if getattr(obj, "is_deleted", False):
        raise HTTPException(status_code=404, detail=detail)
    return obj


def assert_owned(obj, tenant_id: int, detail: str = "Not found") -> None:
    """Raise 404 if obj is None or belongs to another tenant."""
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    if hasattr(obj, "tenant_id") and obj.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=detail)


def cascade_soft_delete_customer(db: Session, customer_id: int, tenant_id: int,
                                 reason: str) -> dict:
    """
    Cascade a customer's soft-delete to dependent rows owned by the same tenant:
      - Active templates       -> is_active=False
      - Custom prices          -> deleted (hard delete; will be re-derived)
      - Future open orders     -> soft-delete (DRAFT, CONFIRMED only)

    Already-delivered/locked orders are kept for audit & history.
    Returns a summary dict for audit logging.
    """
    # Local imports to avoid circular dependency at module load time
    from .models import (
        MasterTemplate, CustomerProductPrice, Order, OrderStatus,
    )

    now = datetime.utcnow()
    summary = {"templates": 0, "prices": 0, "orders": 0}

    # Templates: deactivate (do not hard-delete, history matters)
    tpl_rows = db.execute(
        select(MasterTemplate).where(
            MasterTemplate.tenant_id == tenant_id,
            MasterTemplate.customer_id == customer_id,
            MasterTemplate.is_active == True,
        )
    ).scalars().all()
    for tpl in tpl_rows:
        tpl.is_active = False
        summary["templates"] += 1

    # Custom prices: remove (no soft-delete column on this table)
    price_rows = db.execute(
        select(CustomerProductPrice).where(
            CustomerProductPrice.tenant_id == tenant_id,
            CustomerProductPrice.customer_id == customer_id,
        )
    ).scalars().all()
    for p in price_rows:
        db.delete(p)
        summary["prices"] += 1

    # Future open orders: soft-delete only DRAFT/CONFIRMED ones still in future
    today = now.date()
    open_statuses = {OrderStatus.DRAFT, OrderStatus.CONFIRMED}
    order_rows = db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.customer_id == customer_id,
            Order.is_deleted == False,
            Order.delivery_date >= today,
        )
    ).scalars().all()
    for o in order_rows:
        if o.status in open_statuses:
            o.is_deleted = True
            o.deleted_at = now
            o.deletion_reason = f"cascade: customer deleted ({reason})"
            summary["orders"] += 1

    return summary


def cascade_soft_delete_product(db: Session, product_id: int, tenant_id: int,
                                reason: str) -> dict:
    """
    Cascade a product's soft-delete:
      - Custom prices for this product -> deleted
      - Template items referencing it  -> deleted
      - Future open order LINES        -> deleted (totals recalculated by caller via UI refresh)
    Orders themselves are NOT cascaded.
    """
    from .models import (
        CustomerProductPrice, MasterTemplateItem, OrderLine, Order, OrderStatus,
    )

    summary = {"prices": 0, "template_items": 0, "order_lines": 0}

    for p in db.execute(
        select(CustomerProductPrice).where(
            CustomerProductPrice.tenant_id == tenant_id,
            CustomerProductPrice.product_id == product_id,
        )
    ).scalars().all():
        db.delete(p)
        summary["prices"] += 1

    for ti in db.execute(
        select(MasterTemplateItem).where(
            MasterTemplateItem.tenant_id == tenant_id,
            MasterTemplateItem.product_id == product_id,
        )
    ).scalars().all():
        db.delete(ti)
        summary["template_items"] += 1

    today = datetime.utcnow().date()
    open_statuses = {OrderStatus.DRAFT, OrderStatus.CONFIRMED}
    lines = db.execute(
        select(OrderLine, Order)
        .join(Order, Order.id == OrderLine.order_id)
        .where(
            OrderLine.tenant_id == tenant_id,
            OrderLine.product_id == product_id,
            Order.is_deleted == False,
            Order.delivery_date >= today,
            Order.status.in_(open_statuses),
        )
    ).all()
    for line, _order in lines:
        db.delete(line)
        summary["order_lines"] += 1

    return summary

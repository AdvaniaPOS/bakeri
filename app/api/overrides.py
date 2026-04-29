"""
Order date overrides API.

Lar admin raskt registrere avvik (kunden ringer og vil ha 20 ekstra brød
imorgen) uten å endre den faste malen. Disse overrides anvendes når ordrer
blir generert fra MasterTemplate.

Endpoints:
- GET    /overrides                     liste, filtrer på customer/date-range
- POST   /overrides                     opprett (eller upsert via unique key)
- PUT    /overrides/{id}                full oppdatering
- PATCH  /overrides/{id}                delvis oppdatering
- DELETE /overrides/{id}                slett
- POST   /overrides/bulk                bulk upsert flere linjer på samme dato
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_tenant, get_current_user
from ..auth_models import Tenant, User
from ..models import (
    OrderDateOverride, Customer, Product, AuditLog, AuditAction,
)
from ..schemas import (
    OrderDateOverrideCreate, OrderDateOverrideResponse,
)
from ..tenant_scope import get_or_404

router = APIRouter(prefix="/overrides", tags=["Order Overrides"])


class OverrideUpdate(BaseModel):
    quantity: Optional[int] = Field(None, ge=0)
    reason: Optional[str] = Field(None, max_length=500)


class BulkOverrideLine(BaseModel):
    product_id: int
    quantity: int = Field(..., ge=0)
    reason: Optional[str] = Field(None, max_length=500)


class BulkOverrideRequest(BaseModel):
    customer_id: int
    override_date: date
    lines: List[BulkOverrideLine]


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

@router.get("", response_model=List[OrderDateOverrideResponse])
async def list_overrides(
    customer_id: Optional[int] = None,
    product_id: Optional[int] = None,
    from_date: Optional[date] = Query(None, description="Inkluderer denne datoen"),
    to_date: Optional[date] = Query(None, description="Inkluderer denne datoen"),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    query = select(OrderDateOverride).where(OrderDateOverride.tenant_id == tenant.id)
    if customer_id is not None:
        query = query.where(OrderDateOverride.customer_id == customer_id)
    if product_id is not None:
        query = query.where(OrderDateOverride.product_id == product_id)
    if from_date is not None:
        query = query.where(OrderDateOverride.override_date >= from_date)
    if to_date is not None:
        query = query.where(OrderDateOverride.override_date <= to_date)
    query = query.order_by(
        OrderDateOverride.override_date,
        OrderDateOverride.customer_id,
        OrderDateOverride.product_id,
    )
    rows = db.execute(query).scalars().all()
    return [OrderDateOverrideResponse.model_validate(r) for r in rows]


@router.get("/{override_id}", response_model=OrderDateOverrideResponse)
async def get_override(
    override_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    obj = get_or_404(db, OrderDateOverride, override_id, tenant.id, "Override not found")
    return OrderDateOverrideResponse.model_validate(obj)


# ---------------------------------------------------------------------------
# CREATE / UPSERT
# ---------------------------------------------------------------------------

def _ensure_customer_and_product(db: Session, tenant_id: int, customer_id: int, product_id: int):
    cust = get_or_404(db, Customer, customer_id, tenant_id, "Customer not found")
    prod = get_or_404(db, Product, product_id, tenant_id, "Product not found")
    return cust, prod


def _upsert(db: Session, tenant_id: int, customer_id: int, product_id: int,
            override_date: date, quantity: int, reason: Optional[str],
            user_id: Optional[int]) -> OrderDateOverride:
    """Opprett eller oppdater override basert på (customer, product, date)."""
    existing = db.execute(
        select(OrderDateOverride).where(
            OrderDateOverride.tenant_id == tenant_id,
            OrderDateOverride.customer_id == customer_id,
            OrderDateOverride.product_id == product_id,
            OrderDateOverride.override_date == override_date,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.quantity = quantity
        if reason is not None:
            existing.reason = reason
        return existing

    obj = OrderDateOverride(
        tenant_id=tenant_id,
        customer_id=customer_id,
        product_id=product_id,
        override_date=override_date,
        quantity=quantity,
        reason=reason,
        created_by_user_id=user_id,
    )
    db.add(obj)
    return obj


@router.post("", response_model=OrderDateOverrideResponse, status_code=status.HTTP_201_CREATED)
async def create_override(
    data: OrderDateOverrideCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    _ensure_customer_and_product(db, tenant.id, data.customer_id, data.product_id)
    obj = _upsert(
        db, tenant.id,
        data.customer_id, data.product_id, data.override_date,
        data.quantity, data.reason, user.id,
    )
    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="order_date_override",
        entity_id=obj.id or 0,
        action=AuditAction.CREATE,
        new_values={
            "customer_id": data.customer_id,
            "product_id": data.product_id,
            "override_date": str(data.override_date),
            "quantity": data.quantity,
        },
        user_id=user.id,
    ))
    db.commit()
    db.refresh(obj)
    return OrderDateOverrideResponse.model_validate(obj)


@router.post("/bulk", response_model=List[OrderDateOverrideResponse])
async def bulk_upsert_overrides(
    data: BulkOverrideRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    """
    Bulk upsert for én kunde + én dato. Erstatter / oppretter overrides per produkt.
    Linjer med quantity=0 lagres som "skip" (ikke leveres) — for å fjerne et
    avvik helt, bruk DELETE-endepunktet.
    """
    cust = get_or_404(db, Customer, data.customer_id, tenant.id, "Customer not found")

    # Valider alle produktene først
    product_ids = {ln.product_id for ln in data.lines}
    products = db.execute(
        select(Product).where(
            Product.tenant_id == tenant.id,
            Product.id.in_(product_ids),
        )
    ).scalars().all()
    found_ids = {p.id for p in products}
    missing = product_ids - found_ids
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Products not found: {sorted(missing)}",
        )

    results = []
    for ln in data.lines:
        obj = _upsert(
            db, tenant.id,
            cust.id, ln.product_id, data.override_date,
            ln.quantity, ln.reason, user.id,
        )
        results.append(obj)

    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="order_date_override",
        entity_id=cust.id,
        action=AuditAction.UPDATE,
        new_values={
            "customer_id": cust.id,
            "override_date": str(data.override_date),
            "lines": [{"product_id": l.product_id, "quantity": l.quantity} for l in data.lines],
            "bulk": True,
        },
        user_id=user.id,
    ))
    db.commit()
    for r in results:
        db.refresh(r)
    return [OrderDateOverrideResponse.model_validate(r) for r in results]


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

@router.patch("/{override_id}", response_model=OrderDateOverrideResponse)
async def update_override(
    override_id: int,
    data: OverrideUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    obj = get_or_404(db, OrderDateOverride, override_id, tenant.id, "Override not found")
    old = {"quantity": obj.quantity, "reason": obj.reason}
    update_data = data.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(obj, k, v)
    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="order_date_override",
        entity_id=obj.id,
        action=AuditAction.UPDATE,
        old_values=old,
        new_values=update_data,
        user_id=user.id,
    ))
    db.commit()
    db.refresh(obj)
    return OrderDateOverrideResponse.model_validate(obj)


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

@router.delete("/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_override(
    override_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    obj = get_or_404(db, OrderDateOverride, override_id, tenant.id, "Override not found")
    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="order_date_override",
        entity_id=obj.id,
        action=AuditAction.DELETE,
        old_values={
            "customer_id": obj.customer_id,
            "product_id": obj.product_id,
            "override_date": str(obj.override_date),
            "quantity": obj.quantity,
        },
        user_id=user.id,
    ))
    db.delete(obj)
    db.commit()

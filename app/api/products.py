"""
Product API endpoints. Tenant-scoped.
"""
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_tenant
from ..auth_models import Tenant
from ..models import Product, AuditLog, AuditAction
from ..schemas import (
    ProductCreate, ProductUpdate, ProductResponse, DeleteRequest
)
from ..tenant_scope import get_or_404

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("")
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=20000),
    search: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_available: Optional[bool] = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    query = select(Product).where(
        Product.tenant_id == tenant.id,
        Product.is_deleted == False,
    )
    if is_active is not None:
        query = query.where(Product.is_active == is_active)
    if is_available is not None:
        query = query.where(Product.is_available_for_order == is_available)
    if category:
        query = query.where(Product.category == category)
    if search:
        s = f"%{search}%"
        query = query.where(
            (Product.name.ilike(s))
            | (Product.sku.ilike(s))
            | (Product.description.ilike(s))
        )

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar()
    query = query.order_by(Product.category, Product.name).offset((page - 1) * page_size).limit(page_size)
    products = db.execute(query).scalars().all()

    return {
        "items": [ProductResponse.model_validate(p) for p in products],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/categories")
async def list_categories(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    result = db.execute(
        select(Product.category)
        .where(
            Product.tenant_id == tenant.id,
            Product.is_deleted == False,
            Product.category.isnot(None),
        )
        .distinct()
        .order_by(Product.category)
    ).scalars().all()
    return result


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    product = get_or_404(db, Product, product_id, tenant.id, "Product not found")
    return ProductResponse.model_validate(product)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    existing = db.execute(
        select(Product).where(
            Product.tenant_id == tenant.id,
            Product.sku == data.sku,
            Product.is_deleted == False,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Product with this SKU already exists")

    product = Product(tenant_id=tenant.id, **data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="product",
        entity_id=product.id,
        action=AuditAction.CREATE,
        new_values=data.model_dump(mode="json"),
    )
    db.add(audit)
    db.commit()

    return ProductResponse.model_validate(product)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    product = get_or_404(db, Product, product_id, tenant.id, "Product not found")

    update_data = data.model_dump(exclude_unset=True)
    old_values = {k: getattr(product, k) for k in update_data.keys()}

    for key, value in update_data.items():
        setattr(product, key, value)

    # Marker manuell overstyring av is_active sa Susoft-sync ikke overskriver
    if "is_active" in update_data:
        product.is_active_overridden = True

    db.commit()
    db.refresh(product)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="product",
        entity_id=product.id,
        action=AuditAction.UPDATE,
        old_values=old_values,
        new_values=update_data,
    )
    db.add(audit)
    db.commit()

    return ProductResponse.model_validate(product)


class BulkSetActiveRequest(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=2000)
    is_active: bool


@router.post("/bulk/set-active")
async def bulk_set_active(
    payload: BulkSetActiveRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Sett is_active paa flere produkter samtidig (skjul/vis i bulk)."""
    result = db.execute(
        update(Product)
        .where(
            Product.tenant_id == tenant.id,
            Product.is_deleted == False,
            Product.id.in_(payload.ids),
        )
        .values(is_active=payload.is_active)
    )
    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="product",
        entity_id=0,
        action=AuditAction.UPDATE,
        new_values={"bulk_set_active": payload.is_active, "ids": payload.ids, "updated": result.rowcount},
    ))
    db.commit()
    return {"updated": result.rowcount, "is_active": payload.is_active}


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    delete_request: DeleteRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    product = get_or_404(db, Product, product_id, tenant.id, "Product not found")

    product.is_deleted = True
    product.deleted_at = datetime.utcnow()
    product.deletion_reason = f"{delete_request.reason_category.value}: {delete_request.reason_text}"

    from ..tenant_scope import cascade_soft_delete_product
    cascade = cascade_soft_delete_product(
        db, product.id, tenant.id, delete_request.reason_category.value
    )

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="product",
        entity_id=product.id,
        action=AuditAction.DELETE,
        deletion_reason_category=delete_request.reason_category.value,
        deletion_reason_text=delete_request.reason_text,
        old_values={"sku": product.sku, "name": product.name},
        new_values={"cascade": cascade},
    )
    db.add(audit)
    db.commit()


@router.get("/{product_id}/prices")
async def get_product_customer_prices(
    product_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from ..models import CustomerProductPrice

    get_or_404(db, Product, product_id, tenant.id, "Product not found")

    prices = db.execute(
        select(CustomerProductPrice)
        .where(
            CustomerProductPrice.tenant_id == tenant.id,
            CustomerProductPrice.product_id == product_id,
        )
        .order_by(CustomerProductPrice.customer_id, CustomerProductPrice.effective_from_date.desc())
    ).scalars().all()

    return prices

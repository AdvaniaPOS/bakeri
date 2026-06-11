"""
Master Template API endpoints. Tenant-scoped.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_tenant
from ..auth_models import Tenant
from ..models import MasterTemplate, MasterTemplateItem, Customer, Product, AuditLog, AuditAction
from ..schemas import (
    MasterTemplateCreate, MasterTemplateUpdate, MasterTemplateResponse,
    MasterTemplateItemCreate, MasterTemplateItemUpdate, MasterTemplateItemResponse,
    TemplateMatrixView, ProductResponse
)
from ..tenant_scope import get_or_404
from ..features import feature_required

router = APIRouter(
    prefix="/templates",
    tags=["Master Templates"],
    dependencies=[Depends(feature_required("templates"))],
)


def _get_template(db: Session, template_id: int, tenant_id: int, with_items: bool = False) -> MasterTemplate:
    q = select(MasterTemplate).where(
        MasterTemplate.id == template_id,
        MasterTemplate.tenant_id == tenant_id,
    )
    if with_items:
        q = q.options(selectinload(MasterTemplate.items))
    template = db.execute(q).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.get("", response_model=List[MasterTemplateResponse])
async def list_templates(
    customer_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    query = (
        select(MasterTemplate)
        .where(MasterTemplate.tenant_id == tenant.id)
        .options(selectinload(MasterTemplate.items))
    )
    if customer_id:
        query = query.where(MasterTemplate.customer_id == customer_id)
    if is_active is not None:
        query = query.where(MasterTemplate.is_active == is_active)
    templates = db.execute(query).scalars().all()
    return [MasterTemplateResponse.model_validate(t) for t in templates]


@router.get("/{template_id}", response_model=MasterTemplateResponse)
async def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    template = _get_template(db, template_id, tenant.id, with_items=True)
    return MasterTemplateResponse.model_validate(template)


@router.get("/{template_id}/matrix", response_model=TemplateMatrixView)
async def get_template_matrix(
    template_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    template = _get_template(db, template_id, tenant.id, with_items=True)
    customer = get_or_404(db, Customer, template.customer_id, tenant.id, "Customer not found")

    matrix = {}
    product_ids = set()
    for item in template.items:
        matrix.setdefault(item.product_id, {})[item.day_of_week] = item.quantity
        product_ids.add(item.product_id)

    products = []
    if product_ids:
        products = db.execute(
            select(Product).where(
                Product.tenant_id == tenant.id,
                Product.id.in_(product_ids),
            )
        ).scalars().all()

    return TemplateMatrixView(
        template_id=template.id,
        customer_id=template.customer_id,
        customer_name=customer.name,
        matrix=matrix,
        products=[ProductResponse.model_validate(p) for p in products],
    )


@router.post("", response_model=MasterTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: MasterTemplateCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Customer, data.customer_id, tenant.id, "Customer not found")

    if data.is_active:
        existing_active = db.execute(
            select(MasterTemplate).where(
                MasterTemplate.tenant_id == tenant.id,
                MasterTemplate.customer_id == data.customer_id,
                MasterTemplate.is_active == True,
            )
        ).scalars().all()
        for t in existing_active:
            t.is_active = False

    template = MasterTemplate(
        tenant_id=tenant.id,
        customer_id=data.customer_id,
        name=data.name,
        description=data.description,
        is_active=data.is_active,
    )
    db.add(template)
    db.flush()

    for item_data in (data.items or []):
        get_or_404(db, Product, item_data.product_id, tenant.id, f"Product {item_data.product_id} not found")
        item = MasterTemplateItem(
            tenant_id=tenant.id,
            template_id=template.id,
            product_id=item_data.product_id,
            day_of_week=item_data.day_of_week,
            quantity=item_data.quantity,
            notes=item_data.notes,
        )
        db.add(item)

    db.commit()
    db.refresh(template)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="master_template",
        entity_id=template.id,
        action=AuditAction.CREATE,
        new_values={"customer_id": data.customer_id, "name": data.name},
    )
    db.add(audit)
    db.commit()

    return MasterTemplateResponse.model_validate(template)


@router.patch("/{template_id}", response_model=MasterTemplateResponse)
async def update_template(
    template_id: int,
    data: MasterTemplateUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    template = _get_template(db, template_id, tenant.id, with_items=True)

    if data.is_active and not template.is_active:
        existing_active = db.execute(
            select(MasterTemplate).where(
                MasterTemplate.tenant_id == tenant.id,
                MasterTemplate.customer_id == template.customer_id,
                MasterTemplate.is_active == True,
                MasterTemplate.id != template_id,
            )
        ).scalars().all()
        for t in existing_active:
            t.is_active = False

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(template, key, value)

    db.commit()
    db.refresh(template)
    return MasterTemplateResponse.model_validate(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    template = _get_template(db, template_id, tenant.id)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="master_template",
        entity_id=template.id,
        action=AuditAction.DELETE,
        old_values={"customer_id": template.customer_id, "name": template.name},
    )
    db.add(audit)
    db.delete(template)
    db.commit()


@router.post("/{template_id}/items", status_code=status.HTTP_201_CREATED)
async def add_template_item(
    template_id: int,
    data: MasterTemplateItemCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _get_template(db, template_id, tenant.id)
    get_or_404(db, Product, data.product_id, tenant.id, "Product not found")

    existing = db.execute(
        select(MasterTemplateItem).where(
            MasterTemplateItem.tenant_id == tenant.id,
            MasterTemplateItem.template_id == template_id,
            MasterTemplateItem.product_id == data.product_id,
            MasterTemplateItem.day_of_week == data.day_of_week,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Entry already exists for this product/day. Use PATCH to update.")

    item = MasterTemplateItem(
        tenant_id=tenant.id,
        template_id=template_id,
        product_id=data.product_id,
        day_of_week=data.day_of_week,
        quantity=data.quantity,
        notes=data.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return MasterTemplateItemResponse.model_validate(item)


@router.patch("/{template_id}/items/{item_id}")
async def update_template_item(
    template_id: int,
    item_id: int,
    data: MasterTemplateItemUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _get_template(db, template_id, tenant.id)

    item = db.execute(
        select(MasterTemplateItem).where(
            MasterTemplateItem.tenant_id == tenant.id,
            MasterTemplateItem.id == item_id,
            MasterTemplateItem.template_id == template_id,
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Template item not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)

    db.commit()
    return {"message": "Item updated"}


@router.delete("/{template_id}/items/{item_id}")
async def delete_template_item(
    template_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    _get_template(db, template_id, tenant.id)

    item = db.execute(
        select(MasterTemplateItem).where(
            MasterTemplateItem.tenant_id == tenant.id,
            MasterTemplateItem.id == item_id,
            MasterTemplateItem.template_id == template_id,
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Template item not found")

    db.delete(item)
    db.commit()
    return {"message": "Item deleted"}


@router.put("/{template_id}/matrix")
async def update_template_matrix(
    template_id: int,
    matrix: dict,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    template = _get_template(db, template_id, tenant.id, with_items=True)

    for item in list(template.items):
        db.delete(item)
    # Flush deletes before inserting new rows to avoid UNIQUE
    # constraint conflicts on (template_id, product_id, day_of_week).
    db.flush()

    for product_id_str, days in matrix.items():
        try:
            product_id = int(product_id_str)
        except (TypeError, ValueError):
            continue
        product = db.get(Product, product_id)
        if not product or product.is_deleted or product.tenant_id != tenant.id:
            continue
        for day_str, quantity in (days or {}).items():
            try:
                day_of_week = int(day_str)
                qty = int(quantity)
            except (TypeError, ValueError):
                continue
            if not (1 <= day_of_week <= 7):
                continue
            if qty > 0:
                db.add(MasterTemplateItem(
                    tenant_id=tenant.id,
                    template_id=template_id,
                    product_id=product_id,
                    day_of_week=day_of_week,
                    quantity=qty,
                ))

    db.commit()
    return {"message": "Matrix updated"}


@router.get("/{template_id}/affected-orders")
async def count_affected_orders(
    template_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Tell fremtidige ordrer som kan få oppdaterte linjer fra mal-endringer."""
    from datetime import date as _date
    from ..models import Order, OrderStatus
    from ..cutoff import is_order_locked

    template = _get_template(db, template_id, tenant.id)
    today = _date.today()

    orders = db.execute(
        select(Order).where(
            Order.tenant_id == tenant.id,
            Order.customer_id == template.customer_id,
            Order.delivery_date >= today,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED,
            Order.status != OrderStatus.DELIVERED,
        )
    ).scalars().all()

    draft = sum(1 for o in orders if o.status == OrderStatus.DRAFT and not is_order_locked(o))
    non_draft = sum(1 for o in orders if o.status != OrderStatus.DRAFT and not is_order_locked(o))
    locked = sum(1 for o in orders if is_order_locked(o))

    return {
        "customer_id": template.customer_id,
        "draft_count": draft,
        "non_draft_count": non_draft,
        "locked_count": locked,
        "total_eligible": draft + non_draft,
    }


@router.post("/{template_id}/apply-to-existing-orders")
async def apply_template_to_existing_orders(
    template_id: int,
    include_non_draft: bool = False,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Bygg om ordrelinjer for fremtidige, ikke-låste ordrer basert på malen.

    DRAFT-ordrer oppdateres alltid. Hvis include_non_draft=true oppdateres også
    CONFIRMED / READY_FOR_DELIVERY / IN_TRANSIT (de som ikke er levert,
    kansellert eller låst). Allerede synkede ordrer markeres som PENDING for
    re-sync til SuSoft.
    """
    from datetime import date as _date
    from decimal import Decimal
    from ..models import Order, OrderLine, OrderStatus, SyncStatus
    from ..cutoff import is_order_locked
    from .pricing import get_effective_pricing
    from .orders import calculate_line_totals, recalculate_order_totals

    template = _get_template(db, template_id, tenant.id, with_items=True)
    today = _date.today()

    orders = db.execute(
        select(Order)
        .where(
            Order.tenant_id == tenant.id,
            Order.customer_id == template.customer_id,
            Order.delivery_date >= today,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED,
            Order.status != OrderStatus.DELIVERED,
        )
        .options(selectinload(Order.lines))
    ).scalars().all()

    updated_draft = 0
    updated_non_draft = 0
    skipped_locked = 0
    skipped_non_draft = 0

    for order in orders:
        if is_order_locked(order):
            skipped_locked += 1
            continue
        if order.status != OrderStatus.DRAFT and not include_non_draft:
            skipped_non_draft += 1
            continue

        # Hent linjer fra malen som matcher leveringsdagen.
        weekday = order.delivery_date.isoweekday()
        template_lines = [it for it in template.items if it.day_of_week == weekday]

        # Slett eksisterende linjer.
        for line in list(order.lines):
            db.delete(line)
        db.flush()

        # Bygg nye linjer.
        for tli in template_lines:
            product = db.get(Product, tli.product_id)
            if not product or product.is_deleted or product.tenant_id != tenant.id:
                continue
            unit_price, vat_rate, _is_specific, _price_id = get_effective_pricing(
                db,
                order.customer_id,
                product.id,
                order.delivery_date,
                tenant_id=tenant.id,
                customer=order.customer,
                product=product,
            )
            excl, vat, incl = calculate_line_totals(tli.quantity, unit_price, vat_rate)
            line = OrderLine(
                tenant_id=tenant.id,
                order_id=order.id,
                product_id=product.id,
                quantity=tli.quantity,
                unit_price=unit_price,
                vat_rate=vat_rate,
                line_amount_excl_vat=excl,
                line_vat=vat,
                line_amount_incl_vat=incl,
            )
            db.add(line)

        db.flush()
        db.refresh(order)
        recalculate_order_totals(order)

        # Re-sync hvis allerede sendt til SuSoft.
        if order.sync_status == SyncStatus.SYNCED:
            order.sync_status = SyncStatus.PENDING

        if order.status == OrderStatus.DRAFT:
            updated_draft += 1
        else:
            updated_non_draft += 1

    db.commit()

    return {
        "updated_draft": updated_draft,
        "updated_non_draft": updated_non_draft,
        "skipped_locked": skipped_locked,
        "skipped_non_draft": skipped_non_draft,
        "total_updated": updated_draft + updated_non_draft,
    }


@router.post("/{template_id}/duplicate")
async def duplicate_template(
    template_id: int,
    new_customer_id: Optional[int] = None,
    new_name: Optional[str] = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    template = _get_template(db, template_id, tenant.id, with_items=True)
    target_customer_id = new_customer_id or template.customer_id
    get_or_404(db, Customer, target_customer_id, tenant.id, "Target customer not found")

    new_template = MasterTemplate(
        tenant_id=tenant.id,
        customer_id=target_customer_id,
        name=new_name or f"{template.name} (kopi)",
        description=template.description,
        is_active=False,
    )
    db.add(new_template)
    db.flush()

    for item in template.items:
        new_item = MasterTemplateItem(
            tenant_id=tenant.id,
            template_id=new_template.id,
            product_id=item.product_id,
            day_of_week=item.day_of_week,
            quantity=item.quantity,
            notes=item.notes,
        )
        db.add(new_item)

    db.commit()
    db.refresh(new_template)

    return {"message": "Template duplicated", "new_template_id": new_template.id}

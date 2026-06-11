"""
Pricing API endpoints. Tenant-scoped.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_tenant
from ..auth_models import Tenant
from ..models import (
    CustomerProductPrice, Customer, Product, Order, OrderLine,
    AuditLog, AuditAction, SyncStatus, OrderStatus, CustomerPriceTier
)
from ..schemas import (
    CustomerProductPriceCreate, CustomerProductPriceUpdate,
    CustomerProductPriceResponse, PriceLookupRequest, PriceLookupResponse,
    BatchPriceUpdateRequest, BatchPriceUpdateResponse
)
from ..time_utils import today_oslo, to_naive_utc, now_utc
from ..tenant_scope import get_or_404

router = APIRouter(prefix="/pricing", tags=["Pricing"])


def _normalize_customer_price_tier(value) -> CustomerPriceTier:
    if value == CustomerPriceTier.PRICE_2 or str(value) == CustomerPriceTier.PRICE_2.value:
        return CustomerPriceTier.PRICE_2
    return CustomerPriceTier.PRICE_1


def _resolve_product_pricing(product: Product, price_tier: CustomerPriceTier) -> tuple[Decimal, Decimal]:
    if price_tier == CustomerPriceTier.PRICE_2 and product.alternative_price is not None:
        alternative_vat = product.alternative_vat_rate
        return product.alternative_price, (alternative_vat if alternative_vat is not None else product.vat_rate)
    return product.default_price, product.vat_rate


def _set_line_pricing(line: OrderLine, unit_price: Decimal, vat_rate: Decimal) -> bool:
    excl = (Decimal(line.quantity) * unit_price).quantize(Decimal("0.01"))
    vat = (excl * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
    incl = (excl + vat).quantize(Decimal("0.01"))

    changed = (
        line.unit_price != unit_price
        or line.vat_rate != vat_rate
        or line.line_amount_excl_vat != excl
        or line.line_vat != vat
        or line.line_amount_incl_vat != incl
    )
    if not changed:
        return False

    line.unit_price = unit_price
    line.vat_rate = vat_rate
    line.line_amount_excl_vat = excl
    line.line_vat = vat
    line.line_amount_incl_vat = incl
    line.price_updated_at = to_naive_utc(now_utc())
    return True


def get_effective_pricing(
    db: Session,
    customer_id: int,
    product_id: int,
    target_date: date,
    tenant_id: Optional[int] = None,
    *,
    customer: Optional[Customer] = None,
    product: Optional[Product] = None,
) -> tuple[Decimal, Decimal, bool, Optional[int]]:
    """Get effective price and VAT for a customer/product/date."""
    q = (
        select(CustomerProductPrice)
        .where(
            CustomerProductPrice.customer_id == customer_id,
            CustomerProductPrice.product_id == product_id,
            CustomerProductPrice.effective_from_date <= target_date,
            or_(
                CustomerProductPrice.effective_to_date.is_(None),
                CustomerProductPrice.effective_to_date >= target_date,
            ),
        )
        .order_by(CustomerProductPrice.effective_from_date.desc())
        .limit(1)
    )
    if tenant_id is not None:
        q = q.where(CustomerProductPrice.tenant_id == tenant_id)

    price_entry = db.execute(q).scalar_one_or_none()

    customer_obj = customer or db.get(Customer, customer_id)
    if not customer_obj:
        raise ValueError(f"Customer {customer_id} not found")

    product_obj = product or db.get(Product, product_id)
    if not product_obj:
        raise ValueError(f"Product {product_id} not found")

    price_tier = _normalize_customer_price_tier(getattr(customer_obj, "susoft_price_tier", None))
    base_price, vat_rate = _resolve_product_pricing(product_obj, price_tier)

    if price_entry:
        return (price_entry.price, vat_rate, True, price_entry.id)

    return (base_price, vat_rate, False, None)


def get_effective_price(
    db: Session,
    customer_id: int,
    product_id: int,
    target_date: date,
    tenant_id: Optional[int] = None,
) -> tuple[Decimal, bool, Optional[int]]:
    """
    Get effective price. If tenant_id is provided, queries are tenant-scoped.
    """
    price, _vat_rate, is_customer_specific, price_entry_id = get_effective_pricing(
        db,
        customer_id,
        product_id,
        target_date,
        tenant_id=tenant_id,
    )
    return (price, is_customer_specific, price_entry_id)


@router.post("/lookup", response_model=PriceLookupResponse)
async def lookup_price(
    request: PriceLookupRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Customer, request.customer_id, tenant.id, "Customer not found")
    get_or_404(db, Product, request.product_id, tenant.id, "Product not found")

    try:
        price, is_customer_specific, price_entry_id = get_effective_price(
            db, request.customer_id, request.product_id, request.target_date, tenant_id=tenant.id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return PriceLookupResponse(
        customer_id=request.customer_id,
        product_id=request.product_id,
        target_date=request.target_date,
        effective_price=price,
        is_customer_specific=is_customer_specific,
        price_entry_id=price_entry_id,
    )


@router.get("", response_model=List[CustomerProductPriceResponse])
async def list_prices(
    customer_id: Optional[int] = None,
    product_id: Optional[int] = None,
    include_past: bool = False,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    query = select(CustomerProductPrice).where(CustomerProductPrice.tenant_id == tenant.id)

    if customer_id:
        query = query.where(CustomerProductPrice.customer_id == customer_id)
    if product_id:
        query = query.where(CustomerProductPrice.product_id == product_id)
    if not include_past:
        query = query.where(CustomerProductPrice.effective_from_date >= date.today())

    query = query.order_by(
        CustomerProductPrice.customer_id,
        CustomerProductPrice.product_id,
        CustomerProductPrice.effective_from_date.desc(),
    )
    prices = db.execute(query).scalars().all()
    return [CustomerProductPriceResponse.model_validate(p) for p in prices]


@router.post("", response_model=CustomerProductPriceResponse, status_code=status.HTTP_201_CREATED)
async def create_price(
    data: CustomerProductPriceCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    get_or_404(db, Customer, data.customer_id, tenant.id, "Customer not found")
    get_or_404(db, Product, data.product_id, tenant.id, "Product not found")

    existing = db.execute(
        select(CustomerProductPrice).where(
            CustomerProductPrice.tenant_id == tenant.id,
            CustomerProductPrice.customer_id == data.customer_id,
            CustomerProductPrice.product_id == data.product_id,
            CustomerProductPrice.effective_from_date == data.effective_from_date,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="A price already exists for this customer/product/date combination")

    price_entry = CustomerProductPrice(tenant_id=tenant.id, **data.model_dump())
    db.add(price_entry)
    db.flush()

    previous = db.execute(
        select(CustomerProductPrice)
        .where(
            CustomerProductPrice.tenant_id == tenant.id,
            CustomerProductPrice.customer_id == data.customer_id,
            CustomerProductPrice.product_id == data.product_id,
            CustomerProductPrice.effective_from_date < data.effective_from_date,
            CustomerProductPrice.id != price_entry.id,
            or_(
                CustomerProductPrice.effective_to_date.is_(None),
                CustomerProductPrice.effective_to_date >= data.effective_from_date,
            ),
        )
        .order_by(CustomerProductPrice.effective_from_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if previous:
        previous.effective_to_date = data.effective_from_date - timedelta(days=1)

    db.commit()
    db.refresh(price_entry)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="customer_product_price",
        entity_id=price_entry.id,
        action=AuditAction.PRICE_CHANGE,
        new_values=data.model_dump(mode="json"),
    )
    db.add(audit)
    db.commit()

    if data.effective_from_date <= today_oslo():
        background_tasks.add_task(
            propagate_price_change,
            price_entry.id, data.customer_id, data.product_id, data.effective_from_date, tenant.id
        )

    return CustomerProductPriceResponse.model_validate(price_entry)


@router.patch("/{price_id}", response_model=CustomerProductPriceResponse)
async def update_price(
    price_id: int,
    data: CustomerProductPriceUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    price_entry = get_or_404(db, CustomerProductPrice, price_id, tenant.id, "Price entry not found")

    old_values = {
        "price": float(price_entry.price),
        "effective_from_date": str(price_entry.effective_from_date),
    }

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(price_entry, key, value)

    if "price" in update_data:
        price_entry.orders_updated = False
        price_entry.susoft_sync_triggered = False

    db.commit()
    db.refresh(price_entry)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="customer_product_price",
        entity_id=price_entry.id,
        action=AuditAction.PRICE_CHANGE,
        old_values=old_values,
        new_values={k: str(v) for k, v in update_data.items()},
    )
    db.add(audit)
    db.commit()

    background_tasks.add_task(
        propagate_price_change,
        price_entry.id, price_entry.customer_id, price_entry.product_id,
        price_entry.effective_from_date, tenant.id,
    )

    return CustomerProductPriceResponse.model_validate(price_entry)


@router.delete("/{price_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_price(
    price_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    price_entry = get_or_404(db, CustomerProductPrice, price_id, tenant.id, "Price entry not found")

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="customer_product_price",
        entity_id=price_entry.id,
        action=AuditAction.DELETE,
        old_values={
            "customer_id": price_entry.customer_id,
            "product_id": price_entry.product_id,
            "price": float(price_entry.price),
            "effective_from_date": str(price_entry.effective_from_date),
        },
    )
    db.add(audit)
    db.delete(price_entry)
    db.commit()


@router.post("/propagate", response_model=BatchPriceUpdateResponse)
async def trigger_price_propagation(
    request: BatchPriceUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    price_entry = get_or_404(db, CustomerProductPrice, request.price_entry_id, tenant.id, "Price entry not found")

    affected_orders = db.execute(
        select(OrderLine)
        .join(Order)
        .where(
            Order.tenant_id == tenant.id,
            Order.customer_id == price_entry.customer_id,
            OrderLine.product_id == price_entry.product_id,
            Order.delivery_date >= price_entry.effective_from_date,
            Order.is_locked == False,
            Order.is_deleted == False,
        )
    ).scalars().all()

    if request.update_existing_orders:
        background_tasks.add_task(
            propagate_price_change,
            price_entry.id, price_entry.customer_id, price_entry.product_id,
            price_entry.effective_from_date, tenant.id,
        )

    return BatchPriceUpdateResponse(
        price_entry_id=request.price_entry_id,
        orders_updated=len(affected_orders),
        susoft_sync_scheduled=request.sync_to_susoft,
    )


async def propagate_price_change(
    price_entry_id: int,
    customer_id: int,
    product_id: int,
    effective_from: date,
    tenant_id: int,
):
    """Background task. tenant_id required so we don't cross tenants."""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        price_entry = db.get(CustomerProductPrice, price_entry_id)
        if not price_entry or price_entry.tenant_id != tenant_id:
            return

        customer = db.get(Customer, customer_id)
        if not customer or customer.tenant_id != tenant_id:
            return

        affected_lines = db.execute(
            select(OrderLine)
            .join(Order)
            .where(
                Order.tenant_id == tenant_id,
                Order.customer_id == customer_id,
                OrderLine.product_id == product_id,
                Order.delivery_date >= effective_from,
                Order.is_locked == False,
                Order.is_deleted == False,
            )
        ).scalars().all()

        orders_to_update = set()
        orders_needing_resync = set()

        for line in affected_lines:
            order = db.get(Order, line.order_id)
            product = db.get(Product, line.product_id)
            if not order or not product:
                continue
            new_price, new_vat_rate, _, _ = get_effective_pricing(
                db,
                customer_id,
                product_id,
                order.delivery_date,
                tenant_id=tenant_id,
                customer=customer,
                product=product,
            )
            if _set_line_pricing(line, new_price, new_vat_rate):
                orders_to_update.add(order)

        for order in orders_to_update:
            order.total_amount_excl_vat = sum(l.line_amount_excl_vat for l in order.lines)
            order.total_vat = sum(l.line_vat for l in order.lines)
            order.total_amount_incl_vat = sum(l.line_amount_incl_vat for l in order.lines)
            if order.sync_status == SyncStatus.SYNCED:
                order.sync_status = SyncStatus.PENDING
                order.next_retry_at = None
                orders_needing_resync.add(order.id)

        price_entry.orders_updated = True
        price_entry.susoft_sync_triggered = len(orders_needing_resync) > 0
        db.commit()

        if orders_needing_resync:
            try:
                from ..tasks import sync_order
                for order_id in orders_needing_resync:
                    # Defense-in-depth: _trigger_sync sjekker DRAFT, men
                    # her kaller vi tasken direkte. SYNCED kan i teorien
                    # ikke v\u00e6re DRAFT, men vi kaller via wrapper for trygghet.
                    _o = db.get(Order, order_id)
                    if _o and _o.status != OrderStatus.DRAFT:
                        sync_order.delay(order_id)
            except Exception:
                pass
    finally:
        db.close()


async def propagate_customer_price_tier_change(
    customer_id: int,
    tenant_id: int,
):
    """Reprice unlocked orders when a customer switches SuSoft price tier."""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        customer = db.get(Customer, customer_id)
        if not customer or customer.tenant_id != tenant_id:
            return

        affected_lines = db.execute(
            select(OrderLine)
            .join(Order)
            .where(
                Order.tenant_id == tenant_id,
                Order.customer_id == customer_id,
                Order.is_locked == False,
                Order.is_deleted == False,
            )
        ).scalars().all()

        orders_to_update = set()
        orders_needing_resync = set()

        for line in affected_lines:
            order = db.get(Order, line.order_id)
            product = db.get(Product, line.product_id)
            if not order or not product:
                continue
            new_price, new_vat_rate, _, _ = get_effective_pricing(
                db,
                customer_id,
                line.product_id,
                order.delivery_date,
                tenant_id=tenant_id,
                customer=customer,
                product=product,
            )
            if _set_line_pricing(line, new_price, new_vat_rate):
                orders_to_update.add(order)

        for order in orders_to_update:
            order.total_amount_excl_vat = sum(l.line_amount_excl_vat for l in order.lines)
            order.total_vat = sum(l.line_vat for l in order.lines)
            order.total_amount_incl_vat = sum(l.line_amount_incl_vat for l in order.lines)
            if order.sync_status == SyncStatus.SYNCED:
                order.sync_status = SyncStatus.PENDING
                order.next_retry_at = None
                orders_needing_resync.add(order.id)

        db.commit()

        if orders_needing_resync:
            try:
                from ..tasks import sync_order
                for order_id in orders_needing_resync:
                    order = db.get(Order, order_id)
                    if order and order.status != OrderStatus.DRAFT:
                        sync_order.delay(order_id)
            except Exception:
                pass
    finally:
        db.close()


@router.get("/schedule")
async def get_price_schedule(
    customer_id: Optional[int] = None,
    from_date: date = Query(default_factory=date.today),
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    query = select(CustomerProductPrice).where(
        CustomerProductPrice.tenant_id == tenant.id,
        CustomerProductPrice.effective_from_date >= from_date,
    )
    if customer_id:
        query = query.where(CustomerProductPrice.customer_id == customer_id)
    if to_date:
        query = query.where(CustomerProductPrice.effective_from_date <= to_date)
    query = query.order_by(CustomerProductPrice.effective_from_date)
    return db.execute(query).scalars().all()


@router.get("/pending-updates")
async def get_pending_price_updates(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    prices = db.execute(
        select(CustomerProductPrice).where(
            CustomerProductPrice.tenant_id == tenant.id,
            CustomerProductPrice.effective_from_date <= date.today(),
            CustomerProductPrice.orders_updated == False,
        )
    ).scalars().all()
    return prices

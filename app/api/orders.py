"""
Order management API endpoints. Tenant-scoped.
"""
from datetime import date, timedelta, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_tenant, get_current_user
from ..auth_models import Tenant, User, UserRole
from ..models import (
    Order, OrderLine, OrderStatus, SyncStatus,
    Customer, Product, MasterTemplate, MasterTemplateItem,
    OrderDateOverride, Holiday, CustomerBlockedDate,
    AuditLog, AuditAction, OrderAmendment,
)
from ..schemas import (
    OrderCreate, OrderUpdate, OrderResponse, OrderListResponse,
    OrderLineCreate, OrderLineUpdate, OrderLineResponse,
    OrderAmendmentCreate, OrderAmendmentResponse,
)
from .pricing import get_effective_price
from ..cutoff import ensure_editable, is_order_locked, stamp_locked_at
from ..time_utils import now_oslo, today_oslo, to_naive_utc, now_utc
from ..tenant_scope import get_or_404
from ..holidays_no import is_closed_day
from ..services.order_numbering import allocate_order_no

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders"])


# =============================================================================
# Helpers
# =============================================================================

def calculate_line_totals(quantity: int, unit_price: Decimal, vat_rate: Decimal):
    excl = (Decimal(quantity) * unit_price).quantize(Decimal("0.01"))
    vat = (excl * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
    incl = (excl + vat).quantize(Decimal("0.01"))
    return excl, vat, incl


def recalculate_order_totals(order: Order):
    order.total_amount_excl_vat = sum((l.line_amount_excl_vat for l in order.lines), Decimal("0.00"))
    order.total_vat = sum((l.line_vat for l in order.lines), Decimal("0.00"))
    order.total_amount_incl_vat = sum((l.line_amount_incl_vat for l in order.lines), Decimal("0.00"))


def is_blocked_date(db: Session, customer_id: int, target_date: date, tenant_id: int) -> bool:
    holiday = db.execute(
        select(Holiday).where(
            Holiday.tenant_id == tenant_id,
            Holiday.holiday_date == target_date,
            Holiday.is_full_day == True,
        )
    ).scalar_one_or_none()
    if holiday:
        return True

    blocked = db.execute(
        select(CustomerBlockedDate).where(
            CustomerBlockedDate.tenant_id == tenant_id,
            CustomerBlockedDate.customer_id == customer_id,
            CustomerBlockedDate.start_date <= target_date,
            CustomerBlockedDate.end_date >= target_date,
        )
    ).scalar_one_or_none()
    return blocked is not None


def _trigger_sync(order_id: int):
    try:
        from ..tasks import sync_order
        sync_order.delay(order_id)
    except Exception:
        pass


def _sync_order_inline(db: Session, order: Order) -> None:
    """
    Run SuSoft sync synchronously in the request thread.

    Used as fallback when Celery worker isn't available (typical in dev/local
    setups), so the user gets immediate feedback in the API response instead
    of relying on the 5-minute sweep job.

    Errors are caught and stored on the order; the request still succeeds.
    """
    from ..services.susoft import SuSoftService, SuSoftAPIError
    try:
        service = SuSoftService(db, tenant_id=order.tenant_id)
        service.sync_single_order(order)
        db.commit()
    except (SuSoftAPIError, Exception) as exc:
        db.rollback()
        # Re-load order to mark failure
        fresh = db.get(Order, order.id)
        if fresh:
            fresh.sync_status = SyncStatus.FAILED
            fresh.sync_retry_count = (fresh.sync_retry_count or 0) + 1
            fresh.last_sync_attempt = to_naive_utc(now_utc())
            fresh.sync_error_message = str(exc)[:500]
            db.commit()


def _maybe_push_cart_to_susoft(db: Session, order: Order) -> None:
    """
    Hvis ordren er en SuSoft cart-import (DRAFT, source=susoft_cart_import),
    marker pending_push og forsøk en inline PUT mot SuSoft.

    Ved feil beholdes pending_push=True og Celery-sweeperen prøver igjen.
    Denne funksjonen committer DB-endringer selv.
    """
    if order.source != "susoft_cart_import" or not order.susoft_uuid:
        return
    if order.status != OrderStatus.DRAFT:
        return
    order.susoft_pending_push = True
    db.commit()
    try:
        from ..services.susoft_push import push_order_to_susoft
        push_order_to_susoft(db, order)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        # push_order_to_susoft fanger normalt sine egne feil, men som
        # safety net: rull tilbake og logg.
        db.rollback()
        logger.warning(
            "Inline SuSoft cart-push feilet for order_id=%s: %s",
            order.id, exc,
        )


def _load_order(db: Session, order_id: int, tenant_id: int) -> Order:
    order = db.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id, Order.is_deleted == False)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
            selectinload(Order.amendments),
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _to_response(order: Order) -> dict:
    data = OrderResponse.model_validate(order).model_dump()
    data["customer_name"] = order.customer.name if order.customer else None
    return data


# =============================================================================
# Endpoints
# =============================================================================

@router.get("", response_model=OrderListResponse)
async def list_orders(
    customer_id: Optional[int] = None,
    status_filter: Optional[OrderStatus] = Query(None, alias="status"),
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_hidden: bool = Query(False, description="Inkluder skjulte ordrer (is_deleted=True)"),
    only_hidden: bool = Query(False, description="Vis kun skjulte ordrer"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    base = select(Order).where(Order.tenant_id == tenant.id)
    if only_hidden:
        base = base.where(Order.is_deleted == True)
    elif not include_hidden:
        base = base.where(Order.is_deleted == False)

    if customer_id:
        base = base.where(Order.customer_id == customer_id)
    if status_filter:
        base = base.where(Order.status == status_filter)
    if from_date:
        base = base.where(Order.delivery_date >= from_date)
    if to_date:
        base = base.where(Order.delivery_date <= to_date)

    # Skjul SuSoft-cart-import-ordrer uten reell hente-/leveringsdato.
    # Disse får `delivery_date = today` som fallback ved ingest, men er ikke
    # klare for produksjon før kunden har valgt dato i SuSoft-kassa.
    # NB: bruk `IS DISTINCT FROM` semantikk slik at source=NULL teller som
    # "ikke cart-import" (vanlig SQL `NULL != 'x'` = NULL = falsy).
    base = base.where(
        or_(
            Order.source.is_(None),
            Order.source != "susoft_cart_import",
            Order.susoft_pickup_at.isnot(None),
            Order.susoft_delivery_at.isnot(None),
        )
    )

    # Skjul ordrer uten reell kunde (SuSoft "Ukjent kunde"-placeholder).
    # Disse er kasse-salg uten kundenavn og hører ikke hjemme i et
    # ordresystem for kundebehandling.
    from ..services.susoft_ingest import UKJENT_KUNDE_SUSOFT_ID
    base = base.join(Order.customer).where(
        Customer.susoft_customer_id != UKJENT_KUNDE_SUSOFT_ID,
    )

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0

    orders = db.execute(
        base.options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
        .order_by(Order.delivery_date.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    items = [_to_response(o) for o in orders]
    total_pages = (total + page_size - 1) // page_size

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/by-date/{target_date}")
async def get_orders_by_date(
    target_date: date,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    orders = db.execute(
        select(Order)
        .where(
            Order.tenant_id == tenant.id,
            Order.delivery_date == target_date,
            Order.is_deleted == False,
        )
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
        .order_by(Order.route_position.nullslast(), Order.id)
    ).scalars().all()
    return [_to_response(o) for o in orders]


@router.get("/pending-sync")
async def get_orders_pending_sync(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    orders = db.execute(
        select(Order)
        .where(
            Order.tenant_id == tenant.id,
            Order.sync_status.in_([SyncStatus.PENDING, SyncStatus.FAILED]),
            Order.is_deleted == False,
        )
        .options(selectinload(Order.customer))
        .order_by(Order.delivery_date)
    ).scalars().all()
    return [
        {
            "order_id": o.id,
            "delivery_date": o.delivery_date,
            "customer_name": o.customer.name if o.customer else None,
            "sync_status": o.sync_status.value,
            "sync_retry_count": o.sync_retry_count,
            "sync_error_message": o.sync_error_message,
        }
        for o in orders
    ]


@router.get("/horizon-status")
async def get_horizon_status(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Returnerer status for siste periodeplan-sjekk for innlogget tenant."""
    today = today_oslo()
    last = tenant.last_horizon_check_at
    return {
        "last_check_at": last.isoformat() if last else None,
        "checked_today": bool(last and last.date() == today),
        "today": today.isoformat(),
    }


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    order = _load_order(db, order_id, tenant.id)
    return _to_response(order)


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    customer = get_or_404(db, Customer, data.customer_id, tenant.id, "Customer not found")

    if is_blocked_date(db, customer.id, data.delivery_date, tenant.id):
        raise HTTPException(status_code=400, detail="Delivery date is blocked (holiday or customer-blocked)")

    order = Order(
        tenant_id=tenant.id,
        customer_id=customer.id,
        delivery_date=data.delivery_date,
        status=OrderStatus.DRAFT,
        sync_status=SyncStatus.PENDING,
        internal_notes=data.internal_notes,
        customer_notes=data.customer_notes,
        reference=getattr(data, "reference", None),
    )
    allocate_order_no(db, tenant, order)
    db.add(order)
    db.flush()

    for line_data in data.lines:
        product = get_or_404(db, Product, line_data.product_id, tenant.id, f"Product {line_data.product_id} not found")
        unit_price, _, _ = get_effective_price(db, customer.id, product.id, data.delivery_date, tenant_id=tenant.id)
        excl, vat, incl = calculate_line_totals(line_data.quantity, unit_price, product.vat_rate)
        line = OrderLine(
            tenant_id=tenant.id,
            order_id=order.id,
            product_id=product.id,
            quantity=line_data.quantity,
            unit_price=unit_price,
            vat_rate=product.vat_rate,
            line_amount_excl_vat=excl,
            line_vat=vat,
            line_amount_incl_vat=incl,
            notes=line_data.notes,
        )
        db.add(line)

    db.flush()
    db.refresh(order)
    recalculate_order_totals(order)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="order",
        entity_id=order.id,
        action=AuditAction.CREATE,
        new_values={"customer_id": customer.id, "delivery_date": str(data.delivery_date)},
    )
    db.add(audit)
    db.commit()

    order = _load_order(db, order.id, tenant.id)
    return _to_response(order)


@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: int,
    data: OrderUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    order = _load_order(db, order_id, tenant.id)
    ensure_editable(order, user=user)

    # Snapshot reference foer endring (for auto-amendment hvis ordre er bekreftet/laast)
    old_reference = order.reference
    was_locked_or_confirmed = bool(order.is_locked) or order.status in (
        OrderStatus.CONFIRMED, OrderStatus.READY_FOR_DELIVERY, OrderStatus.DELIVERED
    )

    update_data = data.model_dump(exclude_unset=True)
    if "status" in update_data:
        update_data["status"] = OrderStatus(update_data["status"])
    for key, value in update_data.items():
        setattr(order, key, value)

    # Auto-log endring av referanse paa ordre som har blitt bekreftet/laast
    if was_locked_or_confirmed and "reference" in update_data and old_reference != order.reference:
        amend = OrderAmendment(
            tenant_id=tenant.id,
            order_id=order.id,
            reason=f"Referanse endret fra '{old_reference or '-'}' til '{order.reference or '-'}'",
            reference=order.reference,
            amended_by_name=None,
        )
        db.add(amend)

    if order.sync_status == SyncStatus.SYNCED:
        order.sync_status = SyncStatus.PENDING

    db.commit()

    # Statuser som skal sendes til SuSoft umiddelbart.
    sync_statuses = (
        OrderStatus.CONFIRMED,
        OrderStatus.READY_FOR_DELIVERY,
    )
    if order.status in sync_statuses:
        # Kjør synkront slik at vi får sync_status i responsen.
        # Celery-sweep tar over hvis dette feiler.
        _sync_order_inline(db, order)
        # Trigg også Celery (no-op hvis ikke konfigurert).
        background_tasks.add_task(_trigger_sync, order.id)

    # To-veis sync: hvis dette er en SuSoft cart-import, push endringer tilbake.
    _maybe_push_cart_to_susoft(db, order)

    order = _load_order(db, order.id, tenant.id)
    return _to_response(order)


@router.post("/{order_id}/lines", response_model=OrderLineResponse, status_code=status.HTTP_201_CREATED)
async def add_order_line(
    order_id: int,
    data: OrderLineCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    order = _load_order(db, order_id, tenant.id)
    ensure_editable(order, user=user)

    product = get_or_404(db, Product, data.product_id, tenant.id, "Product not found")
    unit_price, _, _ = get_effective_price(db, order.customer_id, product.id, order.delivery_date, tenant_id=tenant.id)
    excl, vat, incl = calculate_line_totals(data.quantity, unit_price, product.vat_rate)

    line = OrderLine(
        tenant_id=tenant.id,
        order_id=order.id,
        product_id=product.id,
        quantity=data.quantity,
        unit_price=unit_price,
        vat_rate=product.vat_rate,
        line_amount_excl_vat=excl,
        line_vat=vat,
        line_amount_incl_vat=incl,
        notes=data.notes,
        is_adhoc_quantity=True,
    )
    db.add(line)
    db.flush()

    order.is_adhoc_modified = True
    if order.sync_status == SyncStatus.SYNCED:
        order.sync_status = SyncStatus.PENDING

    db.refresh(order)
    recalculate_order_totals(order)
    db.commit()
    db.refresh(line)
    _maybe_push_cart_to_susoft(db, order)
    return OrderLineResponse.model_validate(line)


@router.patch("/{order_id}/lines/{line_id}", response_model=OrderLineResponse)
async def update_order_line(
    order_id: int,
    line_id: int,
    data: OrderLineUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    order = _load_order(db, order_id, tenant.id)
    ensure_editable(order, user=user)

    line = db.execute(
        select(OrderLine).where(
            OrderLine.tenant_id == tenant.id,
            OrderLine.id == line_id,
            OrderLine.order_id == order_id,
        )
    ).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=404, detail="Order line not found")

    update_data = data.model_dump(exclude_unset=True)
    if "quantity" in update_data:
        if line.original_template_quantity is None:
            line.original_template_quantity = line.quantity
        line.quantity = update_data["quantity"]
        line.is_adhoc_quantity = True
        excl, vat, incl = calculate_line_totals(line.quantity, line.unit_price, line.vat_rate)
        line.line_amount_excl_vat = excl
        line.line_vat = vat
        line.line_amount_incl_vat = incl
    if "notes" in update_data:
        line.notes = update_data["notes"]

    order.is_adhoc_modified = True
    if order.sync_status == SyncStatus.SYNCED:
        order.sync_status = SyncStatus.PENDING

    recalculate_order_totals(order)
    db.commit()
    db.refresh(line)
    _maybe_push_cart_to_susoft(db, order)
    return OrderLineResponse.model_validate(line)


@router.delete("/{order_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order_line(
    order_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    order = _load_order(db, order_id, tenant.id)
    ensure_editable(order, user=user)

    line = db.execute(
        select(OrderLine).where(
            OrderLine.tenant_id == tenant.id,
            OrderLine.id == line_id,
            OrderLine.order_id == order_id,
        )
    ).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=404, detail="Order line not found")

    db.delete(line)
    db.flush()

    order.is_adhoc_modified = True
    if order.sync_status == SyncStatus.SYNCED:
        order.sync_status = SyncStatus.PENDING

    db.refresh(order)
    recalculate_order_totals(order)
    db.commit()
    _maybe_push_cart_to_susoft(db, order)


# =============================================================================
# AMENDMENTS / AVVIK
# =============================================================================

@router.get("/{order_id}/amendments", response_model=List[OrderAmendmentResponse])
async def list_amendments(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    order = _load_order(db, order_id, tenant.id)
    rows = db.execute(
        select(OrderAmendment)
        .where(OrderAmendment.tenant_id == tenant.id, OrderAmendment.order_id == order.id)
        .order_by(OrderAmendment.amended_at)
    ).scalars().all()
    return [OrderAmendmentResponse.model_validate(r) for r in rows]


@router.post("/{order_id}/amendments", response_model=OrderAmendmentResponse, status_code=status.HTTP_201_CREATED)
async def create_amendment(
    order_id: int,
    data: OrderAmendmentCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Registrer et avvik / endring paa en ordre. Vises paa leveringsbekreftelsen."""
    from ..dependencies import get_current_user_optional  # local import to avoid cycle
    order = _load_order(db, order_id, tenant.id)

    # Hvis ny referanse oppgis -> oppdater ordre.reference
    if data.reference is not None:
        order.reference = data.reference

    amend = OrderAmendment(
        tenant_id=tenant.id,
        order_id=order.id,
        reason=data.reason,
        reference=data.reference,
        changes_summary=data.changes_summary,
    )
    db.add(amend)
    order.is_adhoc_modified = True
    db.commit()
    db.refresh(amend)
    return OrderAmendmentResponse.model_validate(amend)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    """
    Slett (eller skjul) en ordre.

    - Hvis ordren er overført til SuSoft (har susoft_order_id eller er fakturert):
      Ordren kan IKKE slettes — den blir kun skjult fra standard-listen
      (is_deleted=True), men status og SuSoft-koblinger bevares slik at den kan
      hentes frem igjen via filter.
    - Hvis ordren ikke har vært overført til SuSoft: soft-delete + status=CANCELLED.
    - SUPER_ADMIN kan slette selv om cutoff er passert (override).
    """
    order = _load_order(db, order_id, tenant.id)

    is_in_susoft = bool(order.susoft_order_id) or bool(order.susoft_invoice_no)

    if is_in_susoft:
        # Bare skjul — ikke endre status, ikke rør SuSoft-koblingen.
        order.is_deleted = True
        action_label = "hidden"
    else:
        ensure_editable(order, user=user)
        order.is_deleted = True
        order.status = OrderStatus.CANCELLED
        action_label = "deleted" + (" (admin override)" if user.role in (UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN) and is_order_locked(order) else "")

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="order",
        entity_id=order.id,
        action=AuditAction.DELETE,
        old_values={
            "status": action_label,
            "delivery_date": str(order.delivery_date),
            "susoft_order_id": order.susoft_order_id,
            "susoft_invoice_no": order.susoft_invoice_no,
        },
    )
    db.add(audit)
    db.commit()


@router.post("/{order_id}/restore", response_model=OrderResponse)
async def restore_order(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Gjenopprett en skjult ordre (sett is_deleted=False).

    Brukes for ordrer som er skjult etter overføring til SuSoft, men som man
    likevel vil ha tilbake i den synlige listen.
    """
    order = db.execute(
        select(Order).where(
            Order.id == order_id,
            Order.tenant_id == tenant.id,
        ).options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Ordre ikke funnet")
    if not order.is_deleted:
        return _to_response(order)

    order.is_deleted = False
    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="order",
        entity_id=order.id,
        action=AuditAction.UPDATE,
        new_values={"restored": True},
    )
    db.add(audit)
    db.commit()
    db.refresh(order)
    return _to_response(order)


@router.post("/{order_id}/confirm", response_model=OrderResponse)
async def confirm_order(
    order_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    order = _load_order(db, order_id, tenant.id)
    ensure_editable(order, user=user)

    order.status = OrderStatus.CONFIRMED
    if order.sync_status != SyncStatus.SYNCING:
        order.sync_status = SyncStatus.PENDING

    if is_order_locked(order):
        stamp_locked_at(order)

    db.commit()

    background_tasks.add_task(_trigger_sync, order.id)

    order = _load_order(db, order.id, tenant.id)
    return _to_response(order)


@router.post("/{order_id}/send-to-susoft", response_model=OrderResponse)
async def send_order_to_susoft(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Send ordren til SuSoft (POST /order). Idempotent.

    Dette er en utgående handling, IKKE en redigering — derfor omgår vi
    cutoff-låsen (`ensure_editable`). SuSoft brukes til ordre/faktura, ikke
    produksjonsplanlegging, så det skal alltid være mulig å sende selv etter
    cut-off og etter at leveringsdatoen har passert.

    Returnerer 409 hvis ordren er kansellert, 404 hvis slettet.
    Hvis ordren allerede har `susoft_order_id`, returnerer vi den uendret.
    """
    from ..services.susoft import SuSoftService, SuSoftAPIError
    from ..time_utils import now_utc, to_naive_utc

    order = _load_order(db, order_id, tenant.id)

    if order.is_deleted:
        raise HTTPException(status_code=404, detail="Ordre er slettet")

    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Kansellerte ordrer kan ikke sendes til SuSoft.",
        )

    if order.susoft_order_id:
        # Allerede sendt — idempotent no-op.
        return _to_response(order)

    try:
        service = SuSoftService(db, tenant_id=tenant.id)
        susoft_id = service.create_order(order)
        order.susoft_order_id = susoft_id
        order.sync_status = SyncStatus.SYNCED
        order.last_sync_attempt = to_naive_utc(now_utc())
        order.sync_error_message = None
        db.commit()
    except Exception as exc:
        # tenacity pakker SuSoftAPIError inn i RetryError — pakk ut igjen
        # slik at feilmeldingen til admin blir lesbar.
        from tenacity import RetryError
        original = exc
        if isinstance(exc, RetryError):
            try:
                original = exc.last_attempt.exception() or exc
            except Exception:
                original = exc

        is_data_error = isinstance(original, SuSoftAPIError)
        msg = str(original) or type(original).__name__

        if not is_data_error:
            logger.exception("send_order_to_susoft failed for order %s", order_id)

        db.rollback()
        fresh = db.get(Order, order.id)
        if fresh:
            fresh.sync_status = SyncStatus.FAILED
            fresh.sync_error_message = msg[:500]
            fresh.last_sync_attempt = to_naive_utc(now_utc())
            fresh.sync_retry_count = (fresh.sync_retry_count or 0) + 1
            db.commit()

        # 422 for kjent data-feil (kunde/produkt mangler i SuSoft),
        # 502 for andre nettverks-/server-feil.
        http_status = (
            status.HTTP_422_UNPROCESSABLE_ENTITY if is_data_error
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=http_status,
            detail=f"SuSoft sending feilet: {msg}",
        )

    order = _load_order(db, order.id, tenant.id)
    return _to_response(order)


@router.post("/{order_id}/approve", response_model=OrderResponse)
async def approve_order(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Godkjenn en portal-ordre — fjerner `needs_review`-flagget og markerer
    relaterte popup-varsler som lest. Brukes fra admin-portal når en
    administrator har sett gjennom en ordre fra kunde-portalen.
    """
    from ..models import AdminAlert as _Alert

    order = _load_order(db, order_id, tenant.id)
    if order.is_deleted:
        raise HTTPException(status_code=404, detail="Ordre er slettet")

    now = to_naive_utc(now_utc())
    if order.needs_review:
        order.needs_review = False
        order.reviewed_at = now

    # Marker relaterte portal_order-varsler som lest
    alerts = db.execute(
        select(_Alert).where(
            _Alert.tenant_id == tenant.id,
            _Alert.related_entity_type == "order",
            _Alert.related_entity_id == order.id,
            _Alert.is_read.is_(False),
        )
    ).scalars().all()
    for a in alerts:
        a.is_read = True
        a.read_at = now

    db.commit()
    order = _load_order(db, order.id, tenant.id)
    return _to_response(order)


@router.post("/{order_id}/reset-susoft", response_model=OrderResponse)
async def reset_susoft_link(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Nullstill SuSoft-koblingen p\u00e5 ordren slik at den kan re-sendes.

    Bruksomr\u00e5de: Hvis en ordre ble sendt til SuSoft med feil/manglende data
    (f.eks. uten priser), kan man slette den manuelt i SuSoft og deretter
    nullstille koblingen her, slik at "Send" oppretter en ny.

    NB: Dette sletter ikke noe i SuSoft — det fjerner kun lokal referanse.
    Hvis ordren allerede er fakturert (`susoft_invoice_no`), nektes nullstilling.
    """
    from ..time_utils import now_utc, to_naive_utc

    order = _load_order(db, order_id, tenant.id)

    if order.is_deleted:
        raise HTTPException(status_code=404, detail="Ordre er slettet")

    if order.susoft_invoice_no:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ordre er fakturert i SuSoft. Kan ikke nullstilles.",
        )

    order.susoft_order_id = None
    order.sync_status = SyncStatus.PENDING
    order.sync_error_message = None
    order.sync_retry_count = 0
    order.last_sync_attempt = to_naive_utc(now_utc())
    db.commit()

    order = _load_order(db, order.id, tenant.id)
    return _to_response(order)


@router.post("/{order_id}/invoice", response_model=OrderResponse)
async def invoice_order(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Send ordren som faktura til SuSoft (POST /invoice).

    Dette er en utgående handling, IKKE en redigering — derfor omgår vi
    cutoff-låsen (`ensure_editable`). Tvert imot er det typisk fakturering
    skjer FØR/ETTER levering, og ordren er som regel allerede låst.

    Flyt:
    1. Hvis ordren ikke er sendt til SuSoft enda (mangler `susoft_order_id`),
       kjør `create_order` først (POST /order, idempotent).
    2. Kall `create_invoice` (POST /invoice) som refererer ordren via
       `alternativeId`. Idempotent: returnerer eksisterende fakturanr hvis
       ordren allerede er fakturert.
    3. Stempel `susoft_invoice_no` og `invoiced_at` på ordren.
    """
    from ..services.susoft import SuSoftService, SuSoftAPIError
    from ..time_utils import now_utc, to_naive_utc

    order = _load_order(db, order_id, tenant.id)

    if order.is_deleted:
        raise HTTPException(status_code=404, detail="Ordre er slettet")

    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Kansellerte ordrer kan ikke faktureres.",
        )

    if order.susoft_invoice_no:
        # Allerede fakturert — bare returner gjeldende state.
        return _to_response(order)

    # MIDLERTIDIG SPERRE: SuSoft sin /invoice leser kun fra ORDER-projeksjonen,
    # og ikke fra CART. For cart-import-ordrer (kassesalg fra aPOS) ville vi
    # måttet gjøre POST /order først, som genererer en ny uuid i SuSoft og en
    # parallell ordre-projeksjon. Det skaper duplikater ved neste pull-sync og
    # rot i SuSoft admin. Vi venter med fakturering fra dette systemet til
    # SuSoft tilbyr en "promote cart→order"-rute som beholder cart-uuid'en.
    if order.source == "susoft_cart_import":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Fakturering av aPOS-ordrer er midlertidig deaktivert. "
                "SuSoft mangler en API-rute som lar oss fakturere uten å "
                "opprette en ny ordre-UUID. Faktureres direkte i aPOS inntil videre."
            ),
        )

    try:
        service = SuSoftService(db, tenant_id=tenant.id)

        # Steg 1: Sørg for at ordren finnes i SuSoft først, og at
        # eventuelle lokale endringer er sendt opp.
        if not order.susoft_order_id:
            # Egen-generert ordre som ikke er sendt enda: opprett den først.
            susoft_id = service.create_order(order)
            order.susoft_order_id = susoft_id
            order.sync_status = SyncStatus.SYNCED
            order.last_sync_attempt = to_naive_utc(now_utc())
            order.sync_error_message = None
            db.commit()

        # Steg 2: Lag faktura.
        invoice_no = service.create_invoice(order)
        order.susoft_invoice_no = invoice_no
        order.invoiced_at = to_naive_utc(now_utc())
        # Lås ordren permanent etter fakturering.
        if not order.is_locked:
            order.is_locked = True
            order.locked_at = to_naive_utc(now_utc())
        db.commit()
    except SuSoftAPIError as exc:
        db.rollback()
        # Re-load for å oppdatere feilmeldingen
        fresh = db.get(Order, order.id)
        if fresh:
            fresh.sync_error_message = f"Faktura-feil: {str(exc)[:480]}"
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SuSoft fakturering feilet: {exc}",
        )
    except Exception as exc:
        logger.exception("invoice_order failed for order %s", order_id)
        db.rollback()
        fresh = db.get(Order, order.id)
        if fresh:
            fresh.sync_error_message = f"Faktura-feil: {str(exc)[:480]}"
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Fakturering feilet (intern): {type(exc).__name__}: {exc}",
        )

    order = _load_order(db, order.id, tenant.id)
    return _to_response(order)


@router.post("/generate-from-templates")
async def generate_orders_from_template(
    target_date: date,
    customer_id: Optional[int] = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Auto-generate orders from active master templates for a given date."""
    return _generate_for_date(db, tenant.id, target_date, customer_id)


@router.post("/generate-range")
async def generate_orders_for_range(
    days: int = Query(..., ge=1, le=84, description="Antall dager fremover fra i dag"),
    customer_id: Optional[int] = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Generer ordrer fra aktive maler for et helt periode-vindu fremover.

    Brukes når en bruker trykker «Generer nå» for en kunde — alternativt for
    alle kunder samtidig (uten customer_id). Idempotent: dato med eksisterende
    ordre hoppes over.
    """
    today = today_oslo()
    total_created = 0
    total_skipped = 0
    by_date = []
    for offset in range(days + 1):
        d = today + timedelta(days=offset)
        result = _generate_for_date(db, tenant.id, d, customer_id)
        total_created += result["created_count"]
        total_skipped += result["skipped_count"]
        if result["created_count"] > 0:
            by_date.append({"date": d.isoformat(), "created": result["created_count"]})

    return {
        "from_date": today.isoformat(),
        "to_date": (today + timedelta(days=days)).isoformat(),
        "days": days,
        "created_count": total_created,
        "skipped_count": total_skipped,
        "dates_with_orders": by_date,
    }


@router.post("/ensure-horizon")
async def ensure_order_horizon(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Tving ny sjekk selv om allerede kjørt i dag"),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Sørger for at alle aktive kunder med aktiv mal har ordrer generert
    helt fram til sin konfigurerte horisont (today + order_lead_days).

    - **Idempotent per dag**: Hopper over hvis allerede kjørt i dag (med mindre `force=true`).
    - **Asynkron**: Returnerer 202 umiddelbart; selve genereringen kjører i bakgrunnen.
    - **Concurrency-safe**: In-memory lock per tenant hindrer parallelle kjøringer.

    Brukes ved innlogging og app-mount slik at brukeren alltid har et komplett
    fremtidsbilde uten å vente på den daglige scheduler-jobben.
    """
    today = today_oslo()

    last_check = tenant.last_horizon_check_at
    already_today = (
        last_check is not None
        and last_check.date() == today
    )

    if already_today and not force:
        return {
            "status": "skipped",
            "reason": "already_checked_today",
            "last_check_at": last_check.isoformat(),
        }

    # Dispatch to background — login flow returns instantly.
    background_tasks.add_task(_run_ensure_horizon, tenant.id)

    return {
        "status": "scheduled",
        "tenant_id": tenant.id,
        "last_check_at": last_check.isoformat() if last_check else None,
    }


# In-memory locks per tenant — hindrer at to samtidige kall (login + app-mount)
# kjører jobben dobbelt i samme prosess.
_horizon_locks: dict[int, "threading.Lock"] = {}
_horizon_locks_guard = None


def _get_horizon_lock(tenant_id: int):
    import threading
    global _horizon_locks_guard
    if _horizon_locks_guard is None:
        _horizon_locks_guard = threading.Lock()
    with _horizon_locks_guard:
        lock = _horizon_locks.get(tenant_id)
        if lock is None:
            lock = threading.Lock()
            _horizon_locks[tenant_id] = lock
        return lock


def _run_ensure_horizon(tenant_id: int) -> dict:
    """
    Bakgrunnsjobb: generer manglende ordrer fram til hver kundes horisont.
    Denne kalles fra FastAPI BackgroundTasks og fra startup-hooken.
    """
    import logging
    log = logging.getLogger(__name__)

    lock = _get_horizon_lock(tenant_id)
    if not lock.acquire(blocking=False):
        log.info("ensure_horizon: tenant=%s already running, skipping", tenant_id)
        return {"status": "already_running", "tenant_id": tenant_id}

    from ..database import SessionLocal
    from ..auth_models import Tenant as TenantModel

    db = SessionLocal()
    try:
        today = today_oslo()
        tenant = db.get(TenantModel, tenant_id)
        if not tenant:
            return {"status": "tenant_not_found", "tenant_id": tenant_id}

        # Double-check inne i låsen (kan ha blitt oppdatert siden requesten startet)
        if tenant.last_horizon_check_at and tenant.last_horizon_check_at.date() == today:
            return {"status": "skipped_locked_check", "tenant_id": tenant_id}

        customers = db.execute(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.is_active == True,
                Customer.is_deleted == False,
            )
        ).scalars().all()

        total_created = 0
        per_customer = []

        for cust in customers:
            template = db.execute(
                select(MasterTemplate).where(
                    MasterTemplate.tenant_id == tenant_id,
                    MasterTemplate.customer_id == cust.id,
                    MasterTemplate.is_active == True,
                )
            ).scalar_one_or_none()
            if not template:
                continue

            lead_days = max(1, int(cust.order_lead_days or 14))
            horizon = today + timedelta(days=lead_days)

            last_existing = db.execute(
                select(func.max(Order.delivery_date)).where(
                    Order.tenant_id == tenant_id,
                    Order.customer_id == cust.id,
                    Order.is_deleted == False,
                    Order.delivery_date >= today,
                    Order.delivery_date <= horizon,
                )
            ).scalar()

            start = (last_existing + timedelta(days=1)) if last_existing else today
            if start > horizon:
                continue

            created_for_cust = 0
            d = start
            while d <= horizon:
                result = _generate_for_date(db, tenant_id, d, cust.id)
                created_for_cust += result["created_count"]
                d += timedelta(days=1)

            if created_for_cust > 0:
                total_created += created_for_cust
                per_customer.append({
                    "customer_id": cust.id,
                    "customer_name": cust.name,
                    "created": created_for_cust,
                })

        # Stempling: husk at vi har sjekket i dag
        tenant.last_horizon_check_at = datetime.utcnow()
        db.commit()

        log.info(
            "ensure_horizon: tenant=%s created=%d customers_updated=%d",
            tenant_id, total_created, len(per_customer)
        )
        return {
            "status": "completed",
            "tenant_id": tenant_id,
            "total_created": total_created,
            "customers_updated": per_customer,
        }
    except Exception as exc:
        db.rollback()
        log.exception("ensure_horizon failed for tenant=%s: %s", tenant_id, exc)
        return {"status": "error", "tenant_id": tenant_id, "error": str(exc)}
    finally:
        db.close()
        lock.release()


def _generate_for_date(db: Session, tenant_id: int, target_date: date, customer_id: Optional[int] = None) -> dict:
    """Internal: generate orders from active templates for one date."""
    # Hopp over nasjonale stengte dager (helligdager + julaften/påskeaften)
    if is_closed_day(target_date):
        return {"target_date": target_date.isoformat(), "created_count": 0, "skipped_count": 0, "created": [], "skipped": [], "reason": "closed_day"}

    # Hent tenant-objekt for ordrenr-allokering
    from ..auth_models import Tenant as _TenantModel
    tenant = db.get(_TenantModel, tenant_id)
    if not tenant:
        return {"target_date": target_date.isoformat(), "created_count": 0, "skipped_count": 0, "created": [], "skipped": [], "reason": "tenant_not_found"}

    day_of_week = target_date.weekday() + 1  # 1=Mon..7=Sun

    template_query = (
        select(MasterTemplate)
        .where(
            MasterTemplate.tenant_id == tenant_id,
            MasterTemplate.is_active == True,
        )
        .options(selectinload(MasterTemplate.items))
    )
    if customer_id:
        template_query = template_query.where(MasterTemplate.customer_id == customer_id)

    templates = db.execute(template_query).scalars().all()

    created = []
    skipped = []

    for template in templates:
        cust = db.get(Customer, template.customer_id)
        if not cust or cust.is_deleted or cust.tenant_id != tenant_id:
            continue

        if is_blocked_date(db, cust.id, target_date, tenant_id):
            skipped.append({"customer_id": cust.id, "reason": "blocked_date"})
            continue

        existing = db.execute(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.customer_id == cust.id,
                Order.delivery_date == target_date,
                Order.is_deleted == False,
            )
        ).scalar_one_or_none()
        if existing:
            skipped.append({"customer_id": cust.id, "reason": "already_exists", "order_id": existing.id})
            continue

        items_today = [it for it in template.items if it.day_of_week == day_of_week]

        # apply overrides
        overrides = db.execute(
            select(OrderDateOverride).where(
                OrderDateOverride.tenant_id == tenant_id,
                OrderDateOverride.customer_id == cust.id,
                OrderDateOverride.override_date == target_date,
            )
        ).scalars().all()
        override_map = {o.product_id: o for o in overrides}

        if not items_today and not overrides:
            continue

        order = Order(
            tenant_id=tenant_id,
            customer_id=cust.id,
            delivery_date=target_date,
            status=OrderStatus.DRAFT,
            sync_status=SyncStatus.PENDING,
            generated_from_template_id=template.id,
            reference=template.default_reference,
        )
        allocate_order_no(db, tenant, order)
        db.add(order)
        db.flush()

        product_ids_seen = set()

        for item in items_today:
            product = db.get(Product, item.product_id)
            if not product or product.is_deleted or product.tenant_id != tenant_id:
                continue
            qty = item.quantity
            override = override_map.get(item.product_id)
            if override is not None:
                qty = override.quantity
                override.applied_to_order_id = order.id
            if qty <= 0:
                product_ids_seen.add(item.product_id)
                continue
            unit_price, _, _ = get_effective_price(db, cust.id, product.id, target_date, tenant_id=tenant_id)
            excl, vat, incl = calculate_line_totals(qty, unit_price, product.vat_rate)
            line = OrderLine(
                tenant_id=tenant_id,
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                unit_price=unit_price,
                vat_rate=product.vat_rate,
                line_amount_excl_vat=excl,
                line_vat=vat,
                line_amount_incl_vat=incl,
                original_template_quantity=item.quantity,
                is_adhoc_quantity=(override is not None),
            )
            db.add(line)
            product_ids_seen.add(item.product_id)

        # Apply add-only overrides for products not in template
        for pid, override in override_map.items():
            if pid in product_ids_seen or override.quantity <= 0:
                continue
            product = db.get(Product, pid)
            if not product or product.is_deleted or product.tenant_id != tenant_id:
                continue
            unit_price, _, _ = get_effective_price(db, cust.id, product.id, target_date, tenant_id=tenant_id)
            excl, vat, incl = calculate_line_totals(override.quantity, unit_price, product.vat_rate)
            line = OrderLine(
                tenant_id=tenant_id,
                order_id=order.id,
                product_id=product.id,
                quantity=override.quantity,
                unit_price=unit_price,
                vat_rate=product.vat_rate,
                line_amount_excl_vat=excl,
                line_vat=vat,
                line_amount_incl_vat=incl,
                is_adhoc_quantity=True,
            )
            db.add(line)
            override.applied_to_order_id = order.id

        db.flush()
        db.refresh(order)
        recalculate_order_totals(order)
        created.append({"order_id": order.id, "customer_id": cust.id})

    db.commit()
    return {
        "target_date": target_date,
        "created": created,
        "created_count": len(created),
        "skipped": skipped,
        "skipped_count": len(skipped),
    }

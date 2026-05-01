"""
Sj\u00e5f\u00f8r-API for leverings-bekreftelse (PWA-vennlig).

Endepunkter:
- GET    /driver/today               -- alle leveringer for i dag (eller ?date=)
- POST   /driver/orders/{id}/start   -- markerer ordren som under levering
- POST   /driver/orders/{id}/deliver -- bekreft levering med faktiske antall, foto, signatur
- POST   /driver/orders/{id}/issue   -- registrer avvik

Tilgang: DRIVER, MANAGER, TENANT_ADMIN, SUPER_ADMIN.
"""
from datetime import date as date_t, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth_models import Tenant, User, UserRole
from ..database import get_db
from ..dependencies import get_current_tenant, require_role
from ..models import (
    AuditAction, AuditLog, Customer, DeliveryIssue, DeliveryIssueType,
    Order, OrderLine, OrderStatus,
)
from ..tenant_scope import get_or_404
from ..time_utils import now_oslo, today_oslo

router = APIRouter(prefix="/driver", tags=["Driver"])

DriverDep = require_role(
    UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN,
    UserRole.MANAGER, UserRole.DRIVER,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DriverLine(BaseModel):
    line_id: int
    product_id: int
    product_name: str
    unit: str
    quantity_ordered: int
    delivered_quantity: Optional[int] = None
    waste_quantity: int = 0
    return_quantity: int = 0


class DriverStop(BaseModel):
    order_id: int
    customer_id: int
    customer_name: str
    company_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    delivery_instructions: Optional[str] = None
    delivery_window_start: Optional[str] = None
    delivery_window_end: Optional[str] = None
    route_position: Optional[int] = None
    route_id: Optional[int] = None
    route_name: Optional[str] = None
    status: str
    actual_delivery_time: Optional[datetime] = None
    delivered_by_user_id: Optional[int] = None
    delivery_notes: Optional[str] = None
    delivery_photo_url: Optional[str] = None
    has_signature: bool = False
    total_items: int
    lines: List[DriverLine]


class DriverTodayResponse(BaseModel):
    date: date_t
    stops: List[DriverStop]
    total_stops: int
    total_items: int
    completed_stops: int


class DeliveredLineUpdate(BaseModel):
    line_id: int
    delivered_quantity: int = Field(ge=0)
    waste_quantity: int = Field(default=0, ge=0)
    return_quantity: int = Field(default=0, ge=0)


class DeliverPayload(BaseModel):
    lines: Optional[List[DeliveredLineUpdate]] = None
    notes: Optional[str] = None
    signature_data_url: Optional[str] = Field(
        default=None, max_length=200_000,
        description="Base64 data-URL fra signatur-canvas"
    )
    photo_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000,
        description="Base64 data-URL til foto av leveringen"
    )


class IssuePayload(BaseModel):
    issue_type: DeliveryIssueType
    description: str = Field(min_length=1, max_length=2000)
    quantity_affected: Optional[int] = Field(default=None, ge=0)
    product_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_stop(order: Order) -> DriverStop:
    cust = order.customer
    addr = ", ".join(
        filter(None, [
            cust.street_address if cust else None,
            f"{(cust.postal_code or '').strip()} {(cust.city or '').strip()}".strip() if cust else None,
        ])
    ) if cust else None

    lines: List[DriverLine] = []
    total_items = 0
    for line in order.lines:
        prod = line.product
        total_items += line.quantity
        lines.append(DriverLine(
            line_id=line.id,
            product_id=line.product_id,
            product_name=prod.name if prod else "?",
            unit=prod.unit if prod else "stk",
            quantity_ordered=line.quantity,
            delivered_quantity=line.delivered_quantity,
            waste_quantity=line.waste_quantity or 0,
            return_quantity=line.return_quantity or 0,
        ))

    route = cust.route if cust and cust.route_id else None

    return DriverStop(
        order_id=order.id,
        customer_id=order.customer_id,
        customer_name=cust.name if cust else "?",
        company_name=cust.company_name if cust else None,
        address=addr or None,
        phone=cust.phone if cust else None,
        delivery_instructions=cust.delivery_instructions if cust else None,
        delivery_window_start=cust.delivery_window_start.isoformat() if cust and cust.delivery_window_start else None,
        delivery_window_end=cust.delivery_window_end.isoformat() if cust and cust.delivery_window_end else None,
        route_position=order.route_position,
        route_id=cust.route_id if cust else None,
        route_name=route.name if route else None,
        status=order.status.value if hasattr(order.status, "value") else str(order.status),
        actual_delivery_time=order.actual_delivery_time,
        delivered_by_user_id=order.delivered_by_user_id,
        delivery_notes=order.delivery_notes,
        delivery_photo_url=order.delivery_photo_url,
        has_signature=bool(order.delivery_signature),
        total_items=total_items,
        lines=lines,
    )


def _today_orders(db: Session, tenant_id: int, target: date_t):
    stmt = (
        select(Order)
        .where(
            Order.tenant_id == tenant_id,
            Order.delivery_date == target,
            Order.is_deleted.is_(False),
            Order.status != OrderStatus.CANCELLED,
        )
        .options(
            selectinload(Order.customer).selectinload(Customer.route),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
    )
    orders = db.execute(stmt).scalars().all()
    orders.sort(key=lambda o: (
        (o.customer.route.sort_order if o.customer and o.customer.route else 9999),
        o.route_position if o.route_position is not None else 9999,
        o.customer.name if o.customer else "",
    ))
    return orders


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/today", response_model=DriverTodayResponse)
async def driver_today(
    target: Optional[date_t] = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _user: User = Depends(DriverDep),
) -> DriverTodayResponse:
    target_date = target or today_oslo()
    orders = _today_orders(db, tenant.id, target_date)
    stops = [_serialize_stop(o) for o in orders]
    return DriverTodayResponse(
        date=target_date,
        stops=stops,
        total_stops=len(stops),
        total_items=sum(s.total_items for s in stops),
        completed_stops=sum(1 for s in stops if s.status == OrderStatus.DELIVERED.value),
    )


@router.post("/orders/{order_id}/start", response_model=DriverStop)
async def driver_start_delivery(
    order_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(DriverDep),
) -> DriverStop:
    order = get_or_404(db, Order, order_id, tenant.id, "Ordre ikke funnet")
    if order.status not in (OrderStatus.READY_FOR_DELIVERY, OrderStatus.CONFIRMED, OrderStatus.IN_TRANSIT):
        raise HTTPException(400, f"Kan ikke starte levering n\u00e5r status er {order.status.value}")
    order.status = OrderStatus.IN_TRANSIT
    order.delivered_by_user_id = user.id
    db.commit()
    db.refresh(order)
    # last lines+customer for serialization
    db.execute(
        select(Order).where(Order.id == order.id).options(
            selectinload(Order.customer).selectinload(Customer.route),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
    ).scalar_one()
    return _serialize_stop(order)


@router.post("/orders/{order_id}/deliver", response_model=DriverStop)
async def driver_deliver(
    order_id: int,
    payload: DeliverPayload,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(DriverDep),
) -> DriverStop:
    order = get_or_404(db, Order, order_id, tenant.id, "Ordre ikke funnet")
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(400, "Kan ikke levere en kansellert ordre")

    # Oppdater linjer
    if payload.lines:
        line_map = {l.id: l for l in order.lines}
        for upd in payload.lines:
            line = line_map.get(upd.line_id)
            if not line:
                continue
            line.delivered_quantity = upd.delivered_quantity
            line.waste_quantity = upd.waste_quantity
            line.return_quantity = upd.return_quantity
    else:
        # Default: alt levert som bestilt
        for line in order.lines:
            if line.delivered_quantity is None:
                line.delivered_quantity = line.quantity

    if payload.notes is not None:
        order.delivery_notes = payload.notes.strip() or None
    if payload.signature_data_url:
        order.delivery_signature = payload.signature_data_url
    if payload.photo_data_url:
        order.delivery_photo_url = payload.photo_data_url

    order.status = OrderStatus.DELIVERED
    order.actual_delivery_time = datetime.utcnow()
    order.delivered_by_user_id = user.id

    # Audit
    db.add(AuditLog(
        tenant_id=tenant.id,
        user_id=user.id,
        user_email=user.email,
        entity_type="order",
        entity_id=order.id,
        action=AuditAction.UPDATE,
        new_values={
            "status": "delivered",
            "delivered_by_user_id": user.id,
            "has_photo": bool(payload.photo_data_url),
            "has_signature": bool(payload.signature_data_url),
        },
    ))

    db.commit()
    db.refresh(order)
    return _serialize_stop(order)


@router.post("/orders/{order_id}/issue", status_code=201)
async def driver_report_issue(
    order_id: int,
    payload: IssuePayload,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(DriverDep),
):
    order = get_or_404(db, Order, order_id, tenant.id, "Ordre ikke funnet")
    issue = DeliveryIssue(
        tenant_id=tenant.id,
        order_id=order.id,
        product_id=payload.product_id,
        issue_type=payload.issue_type,
        quantity_affected=payload.quantity_affected,
        description=payload.description.strip(),
        reported_by_user_id=user.id,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return {
        "id": issue.id,
        "order_id": issue.order_id,
        "issue_type": issue.issue_type.value,
        "description": issue.description,
        "quantity_affected": issue.quantity_affected,
        "reported_at": issue.reported_at,
    }

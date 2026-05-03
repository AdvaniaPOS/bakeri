"""
Notifications API — popup-varsler for admin-portalen.

Bruker AdminAlert-tabellen som lagring (sparer migrasjon). Filtrerer på
tenant_id + alert_type='portal_order' for å vise NYE ordrer fra kunde-portalen
som administrator bør se gjennom.

Endepunkter:
- GET  /api/v1/notifications              — liste (default kun uleste)
- GET  /api/v1/notifications/unread-count — bare et tall (lett polling)
- POST /api/v1/notifications/{id}/read    — marker som lest
- POST /api/v1/notifications/read-all     — marker alle som lest
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..auth_models import Tenant, User
from ..database import get_db
from ..dependencies import get_current_tenant, get_current_user
from ..models import AdminAlert, Order

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# Type-konstanter — én enkelt kilde for hvilke alert_types som tolkes som
# "popup-varsler" mot admin (dvs. ikke teknisk sync-feil).
PORTAL_ORDER = "portal_order"
USER_NOTIFICATION_TYPES = (PORTAL_ORDER,)


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    message: str
    severity: str
    is_read: bool
    created_at: datetime
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None
    # Bonus-felter populert for portal_order-varsler
    order_no_display: Optional[str] = None
    customer_name: Optional[str] = None
    delivery_date: Optional[str] = None
    total_amount_incl_vat: Optional[float] = None
    needs_review: Optional[bool] = None

    class Config:
        from_attributes = True


def _enrich(db: Session, alert: AdminAlert, tenant_id: int) -> NotificationOut:
    """Bygger NotificationOut + slår opp relatert ordre hvis aktuelt."""
    out = NotificationOut(
        id=alert.id,
        type=alert.alert_type,
        title=alert.title,
        message=alert.message,
        severity=alert.severity,
        is_read=alert.is_read,
        created_at=alert.created_at,
        related_entity_type=alert.related_entity_type,
        related_entity_id=alert.related_entity_id,
    )
    if alert.alert_type == PORTAL_ORDER and alert.related_entity_id:
        order = db.execute(
            select(Order).where(
                Order.id == alert.related_entity_id,
                Order.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if order is not None:
            out.order_no_display = order.order_no_display
            out.customer_name = order.customer.name if order.customer else None
            out.delivery_date = order.delivery_date.isoformat() if order.delivery_date else None
            out.total_amount_incl_vat = float(order.total_amount_incl_vat or 0)
            out.needs_review = bool(order.needs_review)
    return out


@router.get("", response_model=List[NotificationOut])
def list_notifications(
    unread_only: bool = Query(True, description="Vis kun uleste"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(get_current_user),
):
    q = (
        select(AdminAlert)
        .where(AdminAlert.tenant_id == tenant.id)
        .where(AdminAlert.alert_type.in_(USER_NOTIFICATION_TYPES))
    )
    if unread_only:
        q = q.where(AdminAlert.is_read.is_(False))
    q = q.order_by(AdminAlert.created_at.desc()).limit(limit)

    alerts = db.execute(q).scalars().all()
    return [_enrich(db, a, tenant.id) for a in alerts]


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(get_current_user),
):
    n = db.execute(
        select(func.count(AdminAlert.id))
        .where(AdminAlert.tenant_id == tenant.id)
        .where(AdminAlert.alert_type.in_(USER_NOTIFICATION_TYPES))
        .where(AdminAlert.is_read.is_(False))
    ).scalar_one()
    return {"count": int(n or 0)}


@router.post("/{alert_id}/read")
def mark_read(
    alert_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    alert = db.get(AdminAlert, alert_id)
    if not alert or alert.tenant_id != tenant.id:
        raise HTTPException(404, "Varsel ikke funnet")
    if not alert.is_read:
        alert.is_read = True
        alert.read_at = datetime.utcnow()
        alert.read_by_user_id = user.id
        db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(get_current_user),
):
    alerts = db.execute(
        select(AdminAlert)
        .where(AdminAlert.tenant_id == tenant.id)
        .where(AdminAlert.alert_type.in_(USER_NOTIFICATION_TYPES))
        .where(AdminAlert.is_read.is_(False))
    ).scalars().all()
    now = datetime.utcnow()
    for a in alerts:
        a.is_read = True
        a.read_at = now
        a.read_by_user_id = user.id
    db.commit()
    return {"marked": len(alerts)}

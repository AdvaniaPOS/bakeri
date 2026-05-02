"""
Admin API endpoints.

Handles:
- Panic button (batch cancel/update)
- Holidays management
- Blocked dates
- Alerts
- Audit logs
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth_models import Tenant, User, UserRole, SubscriptionStatus, SubscriptionPlan
from ..auth import get_password_hash
from ..dependencies import get_current_user, get_current_tenant, require_role
from ..crypto_utils import encrypt_secret
from ..email_utils import send_tenant_welcome
from ..models import (
    Order, Holiday, CustomerBlockedDate, AdminAlert, AuditLog,
    OrderStatus, SyncStatus, AuditAction
)
from ..schemas import (
    HolidayCreate, HolidayResponse,
    CustomerBlockedDateCreate, CustomerBlockedDateResponse,
    AdminAlertResponse, AdminAlertAcknowledge,
    AuditLogResponse,
    PanicCancelRequest, PanicCancelResponse
)

router = APIRouter(prefix="/admin", tags=["Admin"])


# =============================================================================
# PANIC BUTTON
# =============================================================================

@router.post("/panic-cancel", response_model=PanicCancelResponse)
async def panic_cancel_orders(
    request: PanicCancelRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    PANIC BUTTON: Batch cancel all orders for a specific date.
    
    Use in emergencies (e.g., power outage, equipment failure).
    
    This will:
    1. Cancel all orders for the target date
    2. Mark synced orders for SuSoft cancellation
    3. Create audit trail entries
    4. Send admin alerts
    """
    query = select(Order).where(
        Order.delivery_date == request.target_date,
        Order.is_deleted == False,
        Order.status.notin_([OrderStatus.CANCELLED, OrderStatus.DELIVERED])
    )
    
    if request.customer_ids:
        query = query.where(Order.customer_id.in_(request.customer_ids))
    
    orders = db.execute(query).scalars().all()
    
    cancelled_count = 0
    failed_count = 0
    susoft_updates = 0
    
    for order in orders:
        try:
            order.status = OrderStatus.CANCELLED
            order.is_deleted = True
            order.deleted_at = datetime.utcnow()
            order.deletion_reason = f"PANIC CANCEL: {request.reason}"
            
            if order.susoft_order_id:
                order.sync_status = SyncStatus.CANCELLED
                susoft_updates += 1
            
            cancelled_count += 1
        except Exception:
            failed_count += 1
    
    # Create master audit log for panic operation
    audit = AuditLog(
        entity_type="panic_cancel",
        entity_id=0,  # Special ID for batch operations
        action=AuditAction.PANIC_CANCEL,
        new_values={
            "target_date": str(request.target_date),
            "reason": request.reason,
            "customer_ids": request.customer_ids,
            "orders_cancelled": cancelled_count
        }
    )
    db.add(audit)
    
    # Create admin alert
    alert = AdminAlert(
        alert_type="panic_cancel",
        severity="critical",
        title=f"PANIC CANCEL: {request.target_date}",
        message=f"{cancelled_count} orders cancelled. Reason: {request.reason}",
        related_entity_type="order",
        related_entity_id=0
    )
    db.add(alert)
    
    db.commit()
    
    # Schedule background sync to SuSoft
    if susoft_updates > 0:
        # background_tasks.add_task(sync_cancelled_orders, request.target_date)
        pass
    
    return PanicCancelResponse(
        target_date=request.target_date,
        orders_cancelled=cancelled_count,
        orders_failed=failed_count,
        susoft_updates_triggered=susoft_updates,
        audit_log_id=audit.id
    )


@router.post("/emergency-lock/{target_date}")
async def emergency_lock_orders(
    target_date: date,
    db: Session = Depends(get_db)
):
    """
    Emergency lock all orders for a date.
    Prevents any further modifications.
    """
    orders = db.execute(
        select(Order).where(
            Order.delivery_date == target_date,
            Order.is_deleted == False,
            Order.is_locked == False
        )
    ).scalars().all()
    
    for order in orders:
        order.is_locked = True
        order.locked_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": f"Locked {len(orders)} orders for {target_date}"}


# =============================================================================
# HOLIDAYS
# =============================================================================

@router.get("/holidays", response_model=List[HolidayResponse])
async def list_holidays(
    year: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    List all holidays.
    """
    query = select(Holiday).order_by(Holiday.holiday_date)
    
    if year:
        query = query.where(Holiday.year == year)
    
    holidays = db.execute(query).scalars().all()
    return [HolidayResponse.model_validate(h) for h in holidays]


@router.post("/holidays", response_model=HolidayResponse, status_code=status.HTTP_201_CREATED)
async def create_holiday(
    data: HolidayCreate,
    db: Session = Depends(get_db)
):
    """
    Add a new holiday.
    Orders on this date will automatically have quantity = 0.
    """
    # Check for duplicate
    existing = db.execute(
        select(Holiday).where(Holiday.holiday_date == data.holiday_date)
    ).scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Holiday already exists for this date"
        )
    
    holiday = Holiday(**data.model_dump())
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    
    return HolidayResponse.model_validate(holiday)


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holiday(
    holiday_id: int,
    db: Session = Depends(get_db)
):
    """
    Remove a holiday.
    """
    holiday = db.get(Holiday, holiday_id)
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    
    db.delete(holiday)
    db.commit()


@router.post("/holidays/populate-norwegian/{year}")
async def populate_norwegian_holidays(
    year: int,
    db: Session = Depends(get_db)
):
    """
    Populate Norwegian public holidays for a given year.
    """
    # Norwegian public holidays
    holidays_data = [
        (date(year, 1, 1), "Nyttårsdag"),
        (date(year, 5, 1), "Arbeidernes dag"),
        (date(year, 5, 17), "Grunnlovsdag"),
        (date(year, 12, 25), "1. juledag"),
        (date(year, 12, 26), "2. juledag"),
    ]
    
    # Easter-dependent holidays (would need proper calculation)
    # For now, skip as they require complex date calculation
    # Easter, Maundy Thursday, Good Friday, Easter Monday, Ascension Day, Whit Sunday, Whit Monday
    
    created = 0
    for holiday_date, name in holidays_data:
        existing = db.execute(
            select(Holiday).where(Holiday.holiday_date == holiday_date)
        ).scalar_one_or_none()
        
        if not existing:
            holiday = Holiday(
                holiday_date=holiday_date,
                name=name,
                year=year,
                is_full_day=True
            )
            db.add(holiday)
            created += 1
    
    db.commit()
    
    return {"message": f"Created {created} holidays for {year}"}


# =============================================================================
# BLOCKED DATES
# =============================================================================

@router.get("/blocked-dates", response_model=List[CustomerBlockedDateResponse])
async def list_blocked_dates(
    customer_id: Optional[int] = None,
    from_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """
    List customer-specific blocked date ranges.
    """
    query = select(CustomerBlockedDate)
    
    if customer_id:
        query = query.where(CustomerBlockedDate.customer_id == customer_id)
    
    if from_date:
        query = query.where(CustomerBlockedDate.end_date >= from_date)
    
    query = query.order_by(CustomerBlockedDate.start_date)
    
    blocked = db.execute(query).scalars().all()
    return [CustomerBlockedDateResponse.model_validate(b) for b in blocked]


@router.post("/blocked-dates", response_model=CustomerBlockedDateResponse, status_code=status.HTTP_201_CREATED)
async def create_blocked_date(
    data: CustomerBlockedDateCreate,
    db: Session = Depends(get_db)
):
    """
    Block a date range for a customer (e.g., summer holidays).
    """
    from ..models import Customer
    
    customer = db.get(Customer, data.customer_id)
    if not customer or customer.is_deleted:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    blocked = CustomerBlockedDate(**data.model_dump())
    db.add(blocked)
    db.commit()
    db.refresh(blocked)
    
    return CustomerBlockedDateResponse.model_validate(blocked)


@router.delete("/blocked-dates/{blocked_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocked_date(
    blocked_id: int,
    db: Session = Depends(get_db)
):
    """
    Remove a blocked date range.
    """
    blocked = db.get(CustomerBlockedDate, blocked_id)
    if not blocked:
        raise HTTPException(status_code=404, detail="Blocked date not found")
    
    db.delete(blocked)
    db.commit()


# =============================================================================
# ALERTS
# =============================================================================

@router.get("/alerts", response_model=List[AdminAlertResponse])
async def list_alerts(
    is_read: Optional[bool] = None,
    is_resolved: Optional[bool] = None,
    severity: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    List admin alerts.
    """
    query = select(AdminAlert)
    
    if is_read is not None:
        query = query.where(AdminAlert.is_read == is_read)
    
    if is_resolved is not None:
        query = query.where(AdminAlert.is_resolved == is_resolved)
    
    if severity:
        query = query.where(AdminAlert.severity == severity)
    
    query = query.order_by(AdminAlert.created_at.desc()).limit(limit)
    
    alerts = db.execute(query).scalars().all()
    return [AdminAlertResponse.model_validate(a) for a in alerts]


@router.get("/alerts/unread-count")
async def get_unread_alert_count(db: Session = Depends(get_db)):
    """
    Get count of unread alerts by severity.
    """
    from sqlalchemy import func
    
    result = db.execute(
        select(AdminAlert.severity, func.count(AdminAlert.id))
        .where(AdminAlert.is_read == False)
        .group_by(AdminAlert.severity)
    ).all()
    
    return {severity: count for severity, count in result}


@router.patch("/alerts/{alert_id}")
async def acknowledge_alert(
    alert_id: int,
    data: AdminAlertAcknowledge,
    db: Session = Depends(get_db)
):
    """
    Mark an alert as read or resolved.
    """
    alert = db.get(AdminAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.is_read = True
    alert.read_at = datetime.utcnow()
    
    if data.resolved:
        alert.is_resolved = True
        alert.resolved_at = datetime.utcnow()
        alert.resolution_notes = data.resolution_notes
    
    db.commit()
    
    return {"message": "Alert acknowledged"}


@router.post("/alerts/mark-all-read")
async def mark_all_alerts_read(db: Session = Depends(get_db)):
    """
    Mark all unread alerts as read.
    """
    alerts = db.execute(
        select(AdminAlert).where(AdminAlert.is_read == False)
    ).scalars().all()
    
    for alert in alerts:
        alert.is_read = True
        alert.read_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": f"Marked {len(alerts)} alerts as read"}


# =============================================================================
# AUDIT LOGS
# =============================================================================

@router.get("/audit-logs", response_model=List[AuditLogResponse])
async def list_audit_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(require_role(UserRole.TENANT_ADMIN, UserRole.SUPER_ADMIN, UserRole.MANAGER)),
):
    """
    Search audit logs with filtering. Tenant-scoped.
    """
    query = select(AuditLog).where(AuditLog.tenant_id == tenant.id)
    
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    
    if action:
        query = query.where(AuditLog.action == action)
    
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    
    if from_date:
        query = query.where(AuditLog.timestamp >= from_date)
    
    if to_date:
        query = query.where(AuditLog.timestamp <= to_date)
    
    query = (
        query
        .order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    
    logs = db.execute(query).scalars().all()
    return [AuditLogResponse.model_validate(log) for log in logs]


@router.get("/audit-logs/deletions")
async def list_deletion_logs(
    from_date: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(require_role(UserRole.TENANT_ADMIN, UserRole.SUPER_ADMIN, UserRole.MANAGER)),
):
    """
    List all deletion audit logs. Tenant-scoped.
    """
    query = select(AuditLog).where(
        AuditLog.tenant_id == tenant.id,
        AuditLog.action == AuditAction.DELETE,
    )
    
    if from_date:
        query = query.where(AuditLog.timestamp >= from_date)
    
    query = (
        query
        .order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    
    logs = db.execute(query).scalars().all()
    return logs


# =============================================================================
# SYSTEM STATUS
# =============================================================================

@router.get("/status")
async def get_system_status(db: Session = Depends(get_db)):
    """
    Get system health status and key metrics.
    """
    from sqlalchemy import func
    
    # Count orders by sync status
    sync_counts = db.execute(
        select(Order.sync_status, func.count(Order.id))
        .where(Order.is_deleted == False)
        .group_by(Order.sync_status)
    ).all()
    
    # Count pending alerts
    alert_count = db.execute(
        select(func.count(AdminAlert.id))
        .where(AdminAlert.is_resolved == False)
    ).scalar()
    
    # Orders for today
    today = date.today()
    today_orders = db.execute(
        select(func.count(Order.id))
        .where(Order.delivery_date == today, Order.is_deleted == False)
    ).scalar()
    
    return {
        "status": "healthy",
        "sync_status_counts": {status.value: count for status, count in sync_counts},
        "pending_alerts": alert_count,
        "orders_today": today_orders,
        "timestamp": datetime.utcnow().isoformat()
    }


# =============================================================================
# SUSOFT SYNC
# =============================================================================

@router.get("/test-connection")
@router.post("/test-connection")
async def test_susoft_connection(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN)),
):
    """
    Test connection to SuSoft API for the current tenant.
    """
    from ..services.susoft import SuSoftService

    try:
        service = SuSoftService(db, tenant_id=tenant.id)
        success = service.test_connection()
        # Refresh tenant to read updated status
        db.refresh(tenant)
        return {
            "success": success,
            "message": "Tilkoblet til SuSoft" if success else (tenant.susoft_last_error or "Kunne ikke koble til SuSoft"),
            "status": tenant.susoft_connection_status,
            "last_check_at": tenant.susoft_last_check_at.isoformat() if tenant.susoft_last_check_at else None,
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
        }


@router.post("/sync/customers")
async def sync_customers_from_susoft(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN)),
):
    """
    Sync customers from SuSoft for the current tenant.
    """
    from ..services.susoft import SuSoftService

    try:
        service = SuSoftService(db, tenant_id=tenant.id)
        results = service.sync_customers_from_susoft()
        return {
            "success": True,
            "message": "Synkronisering fullført",
            **results
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "created": 0,
            "updated": 0
        }


@router.post("/sync/products")
async def sync_products_from_susoft(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN)),
):
    """
    Sync products from SuSoft for the current tenant.
    """
    from ..services.susoft import SuSoftService

    try:
        service = SuSoftService(db, tenant_id=tenant.id)
        results = service.sync_products_from_susoft()
        return {
            "success": True,
            "message": "Synkronisering fullført",
            **results
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "created": 0,
            "updated": 0
        }

# =============================================================================
# SUSOFT CONFIG (per-tenant)
# =============================================================================

from pydantic import BaseModel, EmailStr, Field


class SuSoftConfigResponse(BaseModel):
    api_url: Optional[str] = None
    login: Optional[str] = None
    shop_url_key: Optional[str] = None
    has_password: bool = False
    connection_status: Optional[str] = None
    last_check_at: Optional[datetime] = None
    last_error: Optional[str] = None
    is_locked: bool = True
    can_edit: bool = False  # Beregnes basert paa is_locked + bruker-rolle


class SuSoftConfigUpdate(BaseModel):
    api_url: Optional[str] = Field(default=None, max_length=500)
    login: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, max_length=500)
    shop_url_key: Optional[str] = Field(default=None, max_length=100)


@router.get("/susoft-config", response_model=SuSoftConfigResponse)
async def get_susoft_config(
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN)),
):
    """Hent SuSoft-konfigurasjon for gjeldende tenant. Passordet eksponeres aldri."""
    locked = bool(getattr(tenant, "susoft_config_locked", True))
    can_edit = (user.role == UserRole.SUPER_ADMIN) or not locked
    return SuSoftConfigResponse(
        api_url=tenant.susoft_api_url,
        login=tenant.susoft_login,
        shop_url_key=tenant.susoft_shop_url_key,
        has_password=bool(tenant.susoft_password_encrypted),
        connection_status=tenant.susoft_connection_status,
        last_check_at=tenant.susoft_last_check_at,
        last_error=tenant.susoft_last_error,
        is_locked=locked,
        can_edit=can_edit,
    )


@router.put("/susoft-config", response_model=SuSoftConfigResponse)
async def update_susoft_config(
    payload: SuSoftConfigUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN)),
):
    """Oppdater SuSoft-konfig. Passord lagres kryptert. Låst konfig kan kun endres av SUPER_ADMIN."""
    locked = bool(getattr(tenant, "susoft_config_locked", True))
    if locked and user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Susoft-konfigurasjonen er låst. Kontakt support for å gjøre endringer."
        )
    if payload.api_url is not None:
        tenant.susoft_api_url = payload.api_url.strip() or None
    if payload.login is not None:
        tenant.susoft_login = payload.login.strip() or None
    if payload.shop_url_key is not None:
        tenant.susoft_shop_url_key = payload.shop_url_key.strip() or None
    if payload.password:
        tenant.susoft_password_encrypted = encrypt_secret(payload.password)
    tenant.susoft_connection_status = "unknown"
    db.commit()
    db.refresh(tenant)
    can_edit = (user.role == UserRole.SUPER_ADMIN) or not locked
    return SuSoftConfigResponse(
        api_url=tenant.susoft_api_url,
        login=tenant.susoft_login,
        shop_url_key=tenant.susoft_shop_url_key,
        has_password=bool(tenant.susoft_password_encrypted),
        connection_status=tenant.susoft_connection_status,
        last_check_at=tenant.susoft_last_check_at,
        last_error=tenant.susoft_last_error,
        is_locked=locked,
        can_edit=can_edit,
    )


# =============================================================================
# TENANT-WIDE SETTINGS (lagret som JSON i Tenant.settings)
# =============================================================================

# Whitelist over tillatte settings-nøkler. Verdier valideres pr nøkkel.
_ALLOWED_SETTINGS = {
    # Produksjonsrapport: hvilken dato skal vises som standard?
    # Verdier: "today" | "tomorrow" | int (offset i dager, -7..30)
    "production_report_default_day": {
        "type": "string_or_int",
        "default": "today",
        "description": "Standardvalg for produksjonsrapportens dato",
    },
    # Default leveringsadresse-info som vises på etiketter/utskrift
    "labels_show_phone": {"type": "bool", "default": True, "description": "Vis kundens telefon på etiketter"},
    "labels_show_delivery_window": {"type": "bool", "default": True, "description": "Vis leveringsvindu på etiketter"},
    # PDF-header tekst (overstyrer tenant.name hvis satt)
    "pdf_header_subtitle": {"type": "string", "default": "", "description": "Undertittel som vises i PDF-headeren"},
}


def _validate_setting(key: str, value):
    spec = _ALLOWED_SETTINGS.get(key)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Ukjent innstilling: {key}")
    t = spec["type"]
    if t == "bool" and not isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} må være true/false")
    if t == "string" and not isinstance(value, (str, type(None))):
        raise HTTPException(status_code=400, detail=f"{key} må være tekst")
    if t == "string_or_int":
        if isinstance(value, int):
            if value < -7 or value > 30:
                raise HTTPException(status_code=400, detail=f"{key} må være -7..30")
        elif isinstance(value, str):
            if value not in ("today", "tomorrow") and not value.lstrip("-").isdigit():
                raise HTTPException(status_code=400, detail=f"{key} må være 'today', 'tomorrow' eller heltall")
        else:
            raise HTTPException(status_code=400, detail=f"{key} må være tekst eller heltall")
    return value


@router.get("/settings")
async def get_tenant_settings(
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN, UserRole.MANAGER)),
):
    """Hent alle tenant-innstillinger. Returnerer defaults for nøkler som ikke er satt."""
    current = tenant.settings or {}
    out = {}
    for key, spec in _ALLOWED_SETTINGS.items():
        out[key] = {
            "value": current.get(key, spec["default"]),
            "default": spec["default"],
            "description": spec["description"],
        }
    return out


@router.put("/settings")
async def update_tenant_settings(
    payload: dict,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN)),
):
    """
    Oppdater én eller flere tenant-innstillinger.

    Body: `{"key1": value1, "key2": value2, ...}` — kun nøkler i whitelist tillates.
    """
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="Body må være et JSON-objekt med minst én innstilling")

    new_settings = dict(tenant.settings or {})
    for key, value in payload.items():
        _validate_setting(key, value)
        new_settings[key] = value

    tenant.settings = new_settings
    # SQLAlchemy detekterer ikke alltid endringer i mutable JSON — flagger eksplisitt.
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(tenant, "settings")
    db.commit()
    db.refresh(tenant)
    return {"updated_keys": list(payload.keys()), "settings": tenant.settings}


# =============================================================================
# PERIODEPLAN-HORISONT: manuell trigger fra UI
# =============================================================================

@router.post("/horizon/trigger")
async def trigger_horizon_now(
    background_tasks: BackgroundTasks,
    force: bool = False,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN, UserRole.MANAGER)),
):
    """
    Trigg manuell ordre-generering for innlogget tenant.
    Med `force=true` ignoreres "allerede sjekket i dag"-stempelet.
    """
    from .orders import _run_ensure_horizon

    if force:
        tenant.last_horizon_check_at = None
        db.commit()

    background_tasks.add_task(_run_ensure_horizon, tenant.id)
    return {"status": "scheduled", "tenant_id": tenant.id, "force": force}


# =============================================================================
# SUPER-ADMIN: Tenant management (kunder/portaler)
# =============================================================================

class TenantSummary(BaseModel):
    id: int
    slug: str
    name: str
    legal_name: Optional[str] = None
    email: Optional[str] = None
    is_active: bool
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    user_count: int = 0
    susoft_connection_status: Optional[str] = None
    susoft_config_locked: bool = True
    susoft_has_password: bool = False
    susoft_login: Optional[str] = None
    susoft_shop_url_key: Optional[str] = None
    susoft_api_url: Optional[str] = None

    class Config:
        from_attributes = True


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    email: Optional[EmailStr] = None
    legal_name: Optional[str] = Field(default=None, max_length=255)
    org_number: Optional[str] = Field(default=None, max_length=50)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=128)
    admin_first_name: Optional[str] = Field(default="Admin", max_length=100)
    admin_last_name: Optional[str] = Field(default="Bruker", max_length=100)
    susoft_api_url: Optional[str] = Field(default=None, max_length=500)
    susoft_login: Optional[str] = Field(default=None, max_length=255)
    susoft_password: Optional[str] = Field(default=None, max_length=500)
    susoft_shop_url_key: Optional[str] = Field(default=None, max_length=100)


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    is_active: Optional[bool] = None
    email: Optional[EmailStr] = None
    legal_name: Optional[str] = Field(default=None, max_length=255)


@router.get("/tenants", response_model=List[TenantSummary])
async def list_tenants(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """List alle tenants (kun super-admin)."""
    from sqlalchemy import func
    tenants = db.execute(select(Tenant).order_by(Tenant.id)).scalars().all()
    user_counts = dict(
        db.execute(
            select(User.tenant_id, func.count(User.id)).group_by(User.tenant_id)
        ).all()
    )
    out = []
    for t in tenants:
        out.append(TenantSummary(
            id=t.id,
            slug=t.slug,
            name=t.name,
            legal_name=t.legal_name,
            email=t.email,
            is_active=t.is_active,
            subscription_plan=t.subscription_plan.value if t.subscription_plan else None,
            subscription_status=t.subscription_status.value if t.subscription_status else None,
            user_count=user_counts.get(t.id, 0),
            susoft_connection_status=t.susoft_connection_status,
            susoft_config_locked=bool(getattr(t, "susoft_config_locked", True)),
            susoft_has_password=bool(t.susoft_password_encrypted),
            susoft_login=t.susoft_login,
            susoft_shop_url_key=t.susoft_shop_url_key,
            susoft_api_url=t.susoft_api_url,
        ))
    return out


@router.post("/tenants", response_model=TenantSummary, status_code=201)
async def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Opprett ny tenant + initial admin-bruker (kun super-admin)."""
    existing = db.execute(select(Tenant).where(Tenant.slug == payload.slug)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Tenant med slug '{payload.slug}' finnes allerede")
    existing_user = db.execute(select(User).where(User.email == payload.admin_email)).scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=409, detail=f"Bruker med epost '{payload.admin_email}' finnes allerede")

    tenant = Tenant(
        slug=payload.slug,
        name=payload.name,
        legal_name=payload.legal_name,
        org_number=payload.org_number,
        email=payload.email,
        is_active=True,
        subscription_plan=SubscriptionPlan.STARTER,
        subscription_status=SubscriptionStatus.TRIAL,
        susoft_api_url=payload.susoft_api_url,
        susoft_login=payload.susoft_login,
        susoft_shop_url_key=payload.susoft_shop_url_key,
        susoft_password_encrypted=encrypt_secret(payload.susoft_password) if payload.susoft_password else None,
    )
    db.add(tenant)
    db.flush()

    admin_user = User(
        tenant_id=tenant.id,
        email=payload.admin_email,
        password_hash=get_password_hash(payload.admin_password),
        first_name=payload.admin_first_name or "Admin",
        last_name=payload.admin_last_name or "Bruker",
        role=UserRole.TENANT_ADMIN,
        is_active=True,
        email_verified=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(tenant)

    # Send velkomst-e-post (faller tilbake til logging hvis RESEND_API_KEY mangler)
    try:
        send_tenant_welcome(
            to_email=payload.admin_email,
            tenant_name=tenant.name,
            admin_email=payload.admin_email,
            temp_password=payload.admin_password,
        )
    except Exception:
        pass

    return TenantSummary(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        legal_name=tenant.legal_name,
        email=tenant.email,
        is_active=tenant.is_active,
        subscription_plan=tenant.subscription_plan.value if tenant.subscription_plan else None,
        subscription_status=tenant.subscription_status.value if tenant.subscription_status else None,
        user_count=1,
        susoft_connection_status=tenant.susoft_connection_status,
    )


@router.patch("/tenants/{tenant_id}", response_model=TenantSummary)
async def update_tenant(
    tenant_id: int,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Oppdater tenant (kun super-admin)."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")
    if payload.name is not None:
        tenant.name = payload.name
    if payload.is_active is not None:
        tenant.is_active = payload.is_active
    if payload.email is not None:
        tenant.email = payload.email
    if payload.legal_name is not None:
        tenant.legal_name = payload.legal_name
    db.commit()
    db.refresh(tenant)
    from sqlalchemy import func
    user_count = db.execute(
        select(func.count(User.id)).where(User.tenant_id == tenant.id)
    ).scalar() or 0
    return TenantSummary(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        legal_name=tenant.legal_name,
        email=tenant.email,
        is_active=tenant.is_active,
        subscription_plan=tenant.subscription_plan.value if tenant.subscription_plan else None,
        subscription_status=tenant.subscription_status.value if tenant.subscription_status else None,
        user_count=user_count,
        susoft_connection_status=tenant.susoft_connection_status,
        susoft_config_locked=bool(getattr(tenant, "susoft_config_locked", True)),
        susoft_has_password=bool(tenant.susoft_password_encrypted),
        susoft_login=tenant.susoft_login,
        susoft_shop_url_key=tenant.susoft_shop_url_key,
        susoft_api_url=tenant.susoft_api_url,
    )


# =============================================================================
# SUPER-ADMIN: ENDRE EN HVILKEN SOM HELST TENANTS SUSOFT-KONFIG
# =============================================================================

class TenantSusoftUpdate(BaseModel):
    api_url: Optional[str] = Field(default=None, max_length=500)
    login: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, max_length=500)
    shop_url_key: Optional[str] = Field(default=None, max_length=100)
    config_locked: Optional[bool] = None  # None = uendret


@router.put("/tenants/{tenant_id}/susoft-config")
async def super_admin_update_tenant_susoft(
    tenant_id: int,
    payload: TenantSusoftUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """SUPER_ADMIN: oppdater Susoft-konfig for en hvilken som helst tenant + sett laas."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")
    if payload.api_url is not None:
        tenant.susoft_api_url = payload.api_url.strip() or None
    if payload.login is not None:
        tenant.susoft_login = payload.login.strip() or None
    if payload.shop_url_key is not None:
        tenant.susoft_shop_url_key = payload.shop_url_key.strip() or None
    if payload.password:
        tenant.susoft_password_encrypted = encrypt_secret(payload.password)
    if payload.config_locked is not None:
        tenant.susoft_config_locked = bool(payload.config_locked)
    tenant.susoft_connection_status = "unknown"
    db.commit()
    db.refresh(tenant)
    return {
        "tenant_id": tenant.id,
        "susoft_api_url": tenant.susoft_api_url,
        "susoft_login": tenant.susoft_login,
        "susoft_shop_url_key": tenant.susoft_shop_url_key,
        "susoft_has_password": bool(tenant.susoft_password_encrypted),
        "susoft_config_locked": bool(tenant.susoft_config_locked),
    }


# =============================================================================
# SUPER-ADMIN: IMPERSONATE (logg inn paa en hvilken som helst tenant for support)
# =============================================================================

from ..auth import create_token_pair


@router.post("/tenants/{tenant_id}/impersonate")
async def impersonate_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """
    SUPER_ADMIN: faa et nytt token-par der tenant_id peker paa onsket kunde.
    Beholder rolle SUPER_ADMIN slik at brukeren fortsatt har full tilgang
    og kan returnere til master-portalen naar som helst.
    """
    target_tenant = db.get(Tenant, tenant_id)
    if not target_tenant or not target_tenant.is_active:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet eller inaktiv")

    tokens = create_token_pair(
        user_id=current_user.id,
        tenant_id=target_tenant.id,
        role=current_user.role.value,
        email=current_user.email,
    )
    return {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": tokens.token_type,
        "expires_in": tokens.expires_in,
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role.value,
            "tenant_id": target_tenant.id,
        },
        "tenant": {
            "id": target_tenant.id,
            "name": target_tenant.name,
            "slug": target_tenant.slug,
        },
    }


# =============================================================================
# SUPER-ADMIN: SLETT TENANT (soft / hard)
# =============================================================================

@router.delete("/tenants/{tenant_id}", status_code=200)
async def delete_tenant(
    tenant_id: int,
    hard: bool = Query(default=False, description="True = permanent slett (alle data)"),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """
    Slett tenant.

    - hard=False (default): soft delete - tenant deaktiveres og markeres slettet,
      men data bevares i 30 dager for restore.
    - hard=True: PERMANENT slett av tenant og ALLE relaterte data
      (kunder, produkter, ordrer, brukere). Kan ikke angres.
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")

    if hard:
        # Cascade-delete via relationships (users) + alle tenant-scoped tabeller
        db.delete(tenant)
        db.commit()
        return {"deleted": True, "hard": True, "tenant_id": tenant_id}

    # Soft delete
    tenant.is_active = False
    tenant.is_deleted = True
    tenant.deleted_at = datetime.utcnow()
    tenant.subscription_status = SubscriptionStatus.CANCELLED
    db.commit()
    return {
        "deleted": True,
        "hard": False,
        "tenant_id": tenant_id,
        "restore_until": (datetime.utcnow() + timedelta(days=30)).isoformat(),
    }


@router.post("/tenants/{tenant_id}/restore", status_code=200)
async def restore_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Gjenopprett soft-deleted tenant."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")
    tenant.is_deleted = False
    tenant.deleted_at = None
    tenant.is_active = True
    db.commit()
    return {"restored": True, "tenant_id": tenant_id}


# =============================================================================
# TENANT: BRANDING (logo, farge, navn)  -- TENANT_ADMIN kan endre egne
# =============================================================================

class TenantBrandingUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    primary_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


@router.patch("/tenant/branding")
async def update_own_tenant_branding(
    payload: TenantBrandingUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """
    TENANT_ADMIN kan oppdatere egen tenants branding (navn, logo, farge).
    """
    if current_user.role not in (UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN):
        raise HTTPException(status_code=403, detail="Krever tenant_admin")

    if payload.name is not None:
        tenant.name = payload.name
    if payload.logo_url is not None:
        tenant.logo_url = payload.logo_url.strip() or None
    if payload.primary_color is not None:
        tenant.primary_color = payload.primary_color
    db.commit()
    db.refresh(tenant)
    return {
        "id": tenant.id,
        "name": tenant.name,
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
    }


# =============================================================================
# SUPER-ADMIN: FEATURE FLAGS PER TENANT
# =============================================================================

class TenantFeaturesUpdate(BaseModel):
    features: dict = Field(default_factory=dict)


@router.put("/tenants/{tenant_id}/features")
async def update_tenant_features(
    tenant_id: int,
    payload: TenantFeaturesUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """SUPER_ADMIN: sett feature flags for en tenant. Erstatter hele dict-en."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")
    # Sanitize: kun bool-verdier
    clean = {k: bool(v) for k, v in (payload.features or {}).items() if isinstance(k, str)}
    tenant.features_enabled = clean
    db.commit()
    return {"tenant_id": tenant_id, "features_enabled": clean}


@router.get("/tenants/{tenant_id}/features")
async def get_tenant_features(
    tenant_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")
    from ..features import merged_features
    return {
        "tenant_id": tenant_id,
        "features_enabled": merged_features(tenant),
        "overrides": tenant.features_enabled or {},
    }


@router.get("/features/catalog")
async def get_feature_catalog(
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Liste over alle kjente features med default-verdier."""
    from ..features import FEATURE_CATALOG
    return {"features": FEATURE_CATALOG}


# =============================================================================
# SUPER-ADMIN: RATE-LIMIT KVOTER PER TENANT
# =============================================================================

class TenantRateLimitUpdate(BaseModel):
    """Override for rate-limit (req/min). Sett til null for å bruke plan-default."""
    rate_limit_per_minute: Optional[int] = Field(default=None, ge=1, le=100000)


@router.get("/tenants/{tenant_id}/rate-limit")
async def get_tenant_rate_limit(
    tenant_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Hent gjeldende rate-limit (override + plan-default) for tenant."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")
    from ..rate_limit import PLAN_LIMITS
    override = None
    if tenant.settings:
        raw = tenant.settings.get("rate_limit_per_minute")
        if isinstance(raw, (int, float)) and raw > 0:
            override = int(raw)
    plan_default = PLAN_LIMITS.get(tenant.subscription_plan, PLAN_LIMITS[None])
    return {
        "tenant_id": tenant_id,
        "subscription_plan": tenant.subscription_plan.value if tenant.subscription_plan else None,
        "plan_default_per_minute": plan_default,
        "override_per_minute": override,
        "effective_per_minute": override if override is not None else plan_default,
    }


@router.put("/tenants/{tenant_id}/rate-limit")
async def update_tenant_rate_limit(
    tenant_id: int,
    payload: TenantRateLimitUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """
    SUPER_ADMIN: sett eller fjern override for rate-limit.

    `rate_limit_per_minute=null` ⇒ fjern override (bruk plan-default).
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")
    new_settings = dict(tenant.settings or {})
    if payload.rate_limit_per_minute is None:
        new_settings.pop("rate_limit_per_minute", None)
    else:
        new_settings["rate_limit_per_minute"] = payload.rate_limit_per_minute
    tenant.settings = new_settings
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(tenant, "settings")
    db.commit()
    # Invalider cache umiddelbart slik at neste request bruker ny grense.
    from ..rate_limit import invalidate_tenant_rate_limit
    invalidate_tenant_rate_limit(tenant_id)
    return {
        "tenant_id": tenant_id,
        "rate_limit_per_minute": payload.rate_limit_per_minute,
    }



# =============================================================================
# SUPER-ADMIN: HANDTERE FLERE SUPER-ADMINS
# =============================================================================

class SuperAdminSummary(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class SuperAdminCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(default="Super", max_length=100)
    last_name: str = Field(default="Admin", max_length=100)


PLATFORM_TENANT_SLUG = "platform"


def _ensure_platform_tenant(db: Session) -> Tenant:
    """Hent eller opprett 'platform'-tenant som super-admins tilhorer."""
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == PLATFORM_TENANT_SLUG)
    ).scalar_one_or_none()
    if tenant:
        return tenant
    tenant = Tenant(
        slug=PLATFORM_TENANT_SLUG,
        name="Platform Admin",
        email="support@platform.local",
        is_active=True,
        subscription_plan=SubscriptionPlan.ENTERPRISE,
        subscription_status=SubscriptionStatus.ACTIVE,
    )
    db.add(tenant)
    db.flush()
    return tenant


@router.get("/super-admins", response_model=List[SuperAdminSummary])
async def list_super_admins(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """List alle super-admin-brukere."""
    users = db.execute(
        select(User).where(User.role == UserRole.SUPER_ADMIN).order_by(User.id)
    ).scalars().all()
    return [
        SuperAdminSummary(
            id=u.id,
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            is_active=u.is_active,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/super-admins", response_model=SuperAdminSummary, status_code=201)
async def create_super_admin(
    payload: SuperAdminCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Opprett ny super-admin-bruker (knyttet til platform-tenant)."""
    existing = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Bruker med epost '{payload.email}' finnes allerede")

    platform = _ensure_platform_tenant(db)
    user = User(
        tenant_id=platform.id,
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=UserRole.SUPER_ADMIN,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return SuperAdminSummary(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.delete("/super-admins/{user_id}", status_code=204)
async def delete_super_admin(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Slett super-admin. Kan ikke slette seg selv eller siste gjenvaerende."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Kan ikke slette deg selv")
    target = db.get(User, user_id)
    if not target or target.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=404, detail="Super-admin ikke funnet")
    from sqlalchemy import func
    count = db.execute(
        select(func.count(User.id)).where(
            User.role == UserRole.SUPER_ADMIN, User.is_active == True  # noqa: E712
        )
    ).scalar() or 0
    if count <= 1:
        raise HTTPException(status_code=400, detail="Kan ikke slette siste super-admin")
    db.delete(target)
    db.commit()


# =============================================================================
# GDPR: TENANT-EKSPORT
# =============================================================================

def _serialize_row(obj) -> dict:
    """Konverter SQLAlchemy-rad til dict (kun primitive felter)."""
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name, None)
        if isinstance(v, datetime):
            out[col.name] = v.isoformat()
        elif hasattr(v, "value"):  # Enum
            out[col.name] = v.value
        else:
            out[col.name] = v
    return out


@router.get("/tenant/export")
async def export_tenant_data(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN)),
):
    """
    GDPR-eksport: returner all data tilhorende denne tenanten som JSON.
    Kun TENANT_ADMIN+ for egen tenant.
    """
    from .. import models as m
    from ..auth_models import User as UserModel

    # Tenant-scoped tabeller (TenantMixin)
    tenant_tables = [
        ("routes", m.Route),
        ("route_postal_rules", m.RoutePostalRule),
        ("customers", m.Customer),
        ("products", m.Product),
        ("customer_product_prices", m.CustomerProductPrice),
        ("master_templates", m.MasterTemplate),
        ("master_template_items", m.MasterTemplateItem),
        ("orders", m.Order),
        ("order_lines", m.OrderLine),
        ("order_date_overrides", m.OrderDateOverride),
        ("holidays", m.Holiday),
        ("customer_blocked_dates", m.CustomerBlockedDate),
        ("delivery_routes", m.DeliveryRoute),
        ("delivery_issues", m.DeliveryIssue),
        ("audit_logs", m.AuditLog),
        ("sync_logs", m.SyncLog),
        ("admin_alerts", m.AdminAlert),
        ("daily_production_summary", m.DailyProductionSummary),
        ("production_logs", m.ProductionLog),
    ]

    export: dict = {
        "exported_at": datetime.utcnow().isoformat(),
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "email": tenant.email,
            "subscription_plan": tenant.subscription_plan.value if tenant.subscription_plan else None,
            "logo_url": getattr(tenant, "logo_url", None),
            "primary_color": getattr(tenant, "primary_color", None),
            "settings": getattr(tenant, "settings", None),
            "features_enabled": getattr(tenant, "features_enabled", None),
        },
        "users": [],
        "data": {},
    }

    # Brukere (uten password_hash!)
    users = db.execute(select(UserModel).where(UserModel.tenant_id == tenant.id)).scalars().all()
    for u in users:
        export["users"].append({
            "id": u.id,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "role": u.role.value if u.role else None,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        })

    for key, model in tenant_tables:
        try:
            rows = db.execute(select(model).where(model.tenant_id == tenant.id)).scalars().all()
            export["data"][key] = [_serialize_row(r) for r in rows]
        except Exception as e:
            export["data"][key] = {"error": str(e)}

    headers = {
        "Content-Disposition": f"attachment; filename=tenant-{tenant.slug}-export-{datetime.utcnow().date()}.json",
    }
    return JSONResponse(content=export, headers=headers)


def _build_tenant_export(db: Session, tenant: Tenant) -> dict:
    """Felles helper: bygg full eksport-dict for en tenant. Brukes av backup."""
    from .. import models as m
    from ..auth_models import User as UserModel

    tenant_tables = [
        ("routes", m.Route),
        ("route_postal_rules", m.RoutePostalRule),
        ("customers", m.Customer),
        ("products", m.Product),
        ("customer_product_prices", m.CustomerProductPrice),
        ("master_templates", m.MasterTemplate),
        ("master_template_items", m.MasterTemplateItem),
        ("orders", m.Order),
        ("order_lines", m.OrderLine),
        ("order_date_overrides", m.OrderDateOverride),
        ("holidays", m.Holiday),
        ("customer_blocked_dates", m.CustomerBlockedDate),
        ("delivery_routes", m.DeliveryRoute),
        ("delivery_issues", m.DeliveryIssue),
        ("audit_logs", m.AuditLog),
        ("sync_logs", m.SyncLog),
        ("admin_alerts", m.AdminAlert),
        ("daily_production_summary", m.DailyProductionSummary),
        ("production_logs", m.ProductionLog),
    ]
    export: dict = {
        "exported_at": datetime.utcnow().isoformat(),
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "email": tenant.email,
            "subscription_plan": tenant.subscription_plan.value if tenant.subscription_plan else None,
            "logo_url": getattr(tenant, "logo_url", None),
            "primary_color": getattr(tenant, "primary_color", None),
            "settings": getattr(tenant, "settings", None),
            "features_enabled": getattr(tenant, "features_enabled", None),
        },
        "users": [],
        "data": {},
    }
    users = db.execute(select(UserModel).where(UserModel.tenant_id == tenant.id)).scalars().all()
    for u in users:
        export["users"].append({
            "id": u.id,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "role": u.role.value if u.role else None,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        })
    for key, model in tenant_tables:
        try:
            rows = db.execute(select(model).where(model.tenant_id == tenant.id)).scalars().all()
            export["data"][key] = [_serialize_row(r) for r in rows]
        except Exception as e:
            export["data"][key] = {"error": str(e)}
    return export


@router.get("/tenants/{tenant_id}/backup")
async def backup_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """
    SUPER_ADMIN: last ned full backup (JSON) for en valgt tenant.

    Identisk innhold som /tenant/export, men kan kalles for andre tenants
    enn den innloggede brukeren tilhorer. Egnet for nattlig automatisk
    backup-jobb (curl + lagre til S3/disk).
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant ikke funnet")
    export = _build_tenant_export(db, tenant)
    headers = {
        "Content-Disposition": (
            f"attachment; filename=backup-tenant-{tenant.slug}-"
            f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
        ),
    }
    return JSONResponse(content=export, headers=headers)






"""
Admin API endpoints.

Handles:
- Panic button (batch cancel/update)
- Holidays management
- Blocked dates
- Alerts
- Audit logs
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth_models import Tenant, User, UserRole, SubscriptionStatus, SubscriptionPlan
from ..auth import get_password_hash
from ..dependencies import get_current_user, get_current_tenant, require_role
from ..crypto_utils import encrypt_secret
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
    db: Session = Depends(get_db)
):
    """
    Search audit logs with filtering.
    """
    query = select(AuditLog)
    
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
    db: Session = Depends(get_db)
):
    """
    List all deletion audit logs.
    Useful for compliance and auditing.
    """
    query = select(AuditLog).where(AuditLog.action == AuditAction.DELETE)
    
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


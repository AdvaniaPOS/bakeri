"""
Customer API endpoints. All endpoints are tenant-scoped.
"""
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_tenant
from ..auth_models import Tenant
from ..models import Customer, AuditLog, AuditAction
from ..schemas import (
    CustomerCreate, CustomerUpdate, CustomerResponse,
    CustomerListResponse, DeleteRequest
)
from ..tenant_scope import get_or_404, cascade_soft_delete_customer

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    query = select(Customer).where(
        Customer.tenant_id == tenant.id,
        Customer.is_deleted == False,
    )

    if is_active is not None:
        query = query.where(Customer.is_active == is_active)

    if search:
        s = f"%{search}%"
        query = query.where(
            (Customer.name.ilike(s))
            | (Customer.company_name.ilike(s))
            | (Customer.email.ilike(s))
        )

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar()
    query = query.order_by(Customer.name).offset((page - 1) * page_size).limit(page_size)
    customers = db.execute(query).scalars().all()

    return CustomerListResponse(
        items=[CustomerResponse.model_validate(c) for c in customers],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    customer = get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")
    return CustomerResponse.model_validate(customer)


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    data: CustomerCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    if data.susoft_customer_id:
        existing = db.execute(
            select(Customer).where(
                Customer.tenant_id == tenant.id,
                Customer.susoft_customer_id == data.susoft_customer_id,
                Customer.is_deleted == False,
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="Customer with this SuSoft ID already exists")

    customer = Customer(tenant_id=tenant.id, **data.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="customer",
        entity_id=customer.id,
        action=AuditAction.CREATE,
        new_values=data.model_dump(mode="json"),
    )
    db.add(audit)
    db.commit()

    return CustomerResponse.model_validate(customer)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    customer = get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")

    update_data = data.model_dump(exclude_unset=True)
    old_values = {k: getattr(customer, k) for k in update_data.keys()}

    for key, value in update_data.items():
        setattr(customer, key, value)

    db.commit()
    db.refresh(customer)

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="customer",
        entity_id=customer.id,
        action=AuditAction.UPDATE,
        old_values=old_values,
        new_values=update_data,
    )
    db.add(audit)
    db.commit()

    return CustomerResponse.model_validate(customer)


class BulkSetActiveRequest(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=1000)
    is_active: bool


@router.post("/bulk/set-active")
async def bulk_set_active(
    payload: BulkSetActiveRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Sett is_active paa flere kunder samtidig (skjul/vis i bulk)."""
    result = db.execute(
        update(Customer)
        .where(
            Customer.tenant_id == tenant.id,
            Customer.is_deleted == False,
            Customer.id.in_(payload.ids),
        )
        .values(is_active=payload.is_active)
    )
    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="customer",
        entity_id=0,
        action=AuditAction.UPDATE,
        new_values={"bulk_set_active": payload.is_active, "ids": payload.ids, "updated": result.rowcount},
    ))
    db.commit()
    return {"updated": result.rowcount, "is_active": payload.is_active}


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: int,
    delete_request: DeleteRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    customer = get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")

    customer.is_deleted = True
    customer.deleted_at = datetime.utcnow()
    customer.deletion_reason = f"{delete_request.reason_category.value}: {delete_request.reason_text}"

    cascade = cascade_soft_delete_customer(
        db, customer.id, tenant.id, delete_request.reason_category.value
    )

    audit = AuditLog(
        tenant_id=tenant.id,
        entity_type="customer",
        entity_id=customer.id,
        action=AuditAction.DELETE,
        deletion_reason_category=delete_request.reason_category.value,
        deletion_reason_text=delete_request.reason_text,
        old_values={"name": customer.name, "email": customer.email},
        new_values={"cascade": cascade},
    )
    db.add(audit)
    db.commit()


@router.get("/{customer_id}/prices")
async def get_customer_prices(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from ..models import CustomerProductPrice

    get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")

    prices = db.execute(
        select(CustomerProductPrice)
        .where(
            CustomerProductPrice.tenant_id == tenant.id,
            CustomerProductPrice.customer_id == customer_id,
        )
        .order_by(CustomerProductPrice.product_id, CustomerProductPrice.effective_from_date.desc())
    ).scalars().all()

    return prices


@router.get("/{customer_id}/orders")
async def get_customer_orders(
    customer_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from ..models import Order

    get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")

    query = (
        select(Order)
        .where(
            Order.tenant_id == tenant.id,
            Order.customer_id == customer_id,
            Order.is_deleted == False,
        )
        .order_by(Order.delivery_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    return db.execute(query).scalars().all()


@router.get("/{customer_id}/template")
async def get_customer_template(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from ..models import MasterTemplate

    get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")

    template = db.execute(
        select(MasterTemplate)
        .where(
            MasterTemplate.tenant_id == tenant.id,
            MasterTemplate.customer_id == customer_id,
            MasterTemplate.is_active == True,
        )
        .options(selectinload(MasterTemplate.items))
    ).scalar_one_or_none()

    if not template:
        raise HTTPException(status_code=404, detail="No active template found for customer")

    return template


@router.get("/{customer_id}/plan-status")
async def get_customer_plan_status(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Statusinformasjon for kundens periodeplan:
    - om kunden er aktiv (genererer ordrer)
    - om det finnes en aktiv mal
    - hvor mange dager fremover ordrer skal genereres
    - antall fremtidige ordrer som ligger i systemet
    - lengste leveringsdato vi har generert til
    """
    from datetime import date as _date
    from sqlalchemy import and_
    from ..models import MasterTemplate, Order

    customer = get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")

    template = db.execute(
        select(MasterTemplate)
        .where(
            MasterTemplate.tenant_id == tenant.id,
            MasterTemplate.customer_id == customer_id,
            MasterTemplate.is_active == True,
        )
    ).scalar_one_or_none()

    today = _date.today()
    future_orders_count = db.execute(
        select(func.count(Order.id)).where(
            Order.tenant_id == tenant.id,
            Order.customer_id == customer_id,
            Order.is_deleted == False,
            Order.delivery_date >= today,
        )
    ).scalar() or 0

    last_date = db.execute(
        select(func.max(Order.delivery_date)).where(
            Order.tenant_id == tenant.id,
            Order.customer_id == customer_id,
            Order.is_deleted == False,
        )
    ).scalar()

    return {
        "customer_id": customer.id,
        "is_active": customer.is_active,
        "order_lead_days": customer.order_lead_days,
        "weeks_ahead": round(customer.order_lead_days / 7, 1),
        "has_active_template": template is not None,
        "template_id": template.id if template else None,
        "template_name": template.name if template else None,
        "future_orders_count": future_orders_count,
        "last_generated_date": last_date.isoformat() if last_date else None,
        "delivers_on_holidays": customer.delivers_on_holidays,
    }


# =============================================================================
# Multi-utsalg + portal-bruker
# =============================================================================

class OutletSummary(BaseModel):
    id: int
    name: str
    company_name: Optional[str] = None
    street_address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    is_active: bool
    has_portal_user: bool = False

    model_config = {"from_attributes": True}


@router.get("/{customer_id}/outlets", response_model=List[OutletSummary])
async def list_outlets(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Liste over utsalg under en hovedkunde."""
    from ..auth_models import User as _User
    parent = get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")
    outlets = db.execute(
        select(Customer).where(
            Customer.tenant_id == tenant.id,
            Customer.parent_customer_id == parent.id,
            Customer.is_deleted == False,
        ).order_by(Customer.name)
    ).scalars().all()
    # Sjekk hvilke utsalg som har egen portal-bruker
    user_ids = set(db.execute(
        select(_User.customer_id).where(
            _User.tenant_id == tenant.id,
            _User.customer_id.in_([o.id for o in outlets] or [0]),
            _User.is_deleted == False,
        )
    ).scalars().all())
    return [
        OutletSummary(
            id=o.id, name=o.name, company_name=o.company_name,
            street_address=o.street_address, postal_code=o.postal_code,
            city=o.city, is_active=o.is_active,
            has_portal_user=o.id in user_ids,
        )
        for o in outlets
    ]


class OutletCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    street_address: Optional[str] = Field(None, max_length=500)
    postal_code: Optional[str] = Field(None, max_length=20)
    city: Optional[str] = Field(None, max_length=100)
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    delivery_instructions: Optional[str] = Field(None, max_length=2000)


@router.post("/{customer_id}/outlets", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_outlet(
    customer_id: int,
    data: OutletCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Opprett et utsalg under en hovedkunde."""
    parent = get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")
    if parent.parent_customer_id is not None:
        raise HTTPException(status_code=400, detail="Utsalg kan ikke ha egne under-utsalg")
    outlet = Customer(
        tenant_id=tenant.id,
        parent_customer_id=parent.id,
        order_lead_days=parent.order_lead_days,
        delivers_on_holidays=parent.delivers_on_holidays,
        country=parent.country,
        **data.model_dump(),
    )
    db.add(outlet)
    db.commit()
    db.refresh(outlet)
    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="customer",
        entity_id=outlet.id,
        action=AuditAction.CREATE,
        new_values={"created_as_outlet_of": parent.id, **data.model_dump(mode="json")},
    ))
    db.commit()
    return CustomerResponse.model_validate(outlet)


class PortalUserInvite(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    initial_password: str = Field(..., min_length=8, max_length=128)


class PortalUserResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    customer_id: int
    is_active: bool


@router.get("/{customer_id}/portal-users", response_model=List[PortalUserResponse])
async def list_portal_users(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    from ..auth_models import User as _User, UserRole as _UserRole
    customer = get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")
    users = db.execute(
        select(_User).where(
            _User.tenant_id == tenant.id,
            _User.customer_id == customer.id,
            _User.role == _UserRole.CUSTOMER_PORTAL,
            _User.is_deleted == False,
        ).order_by(_User.email)
    ).scalars().all()
    return [
        PortalUserResponse(
            id=u.id, email=u.email, first_name=u.first_name,
            last_name=u.last_name, customer_id=u.customer_id, is_active=u.is_active,
        ) for u in users
    ]


@router.post("/{customer_id}/portal-users", response_model=PortalUserResponse, status_code=status.HTTP_201_CREATED)
async def create_portal_user(
    customer_id: int,
    data: PortalUserInvite,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Opprett en kundeportal-bruker som er knyttet til denne kunden (eller utsalget)."""
    from ..auth_models import User as _User, UserRole as _UserRole
    from ..auth import get_password_hash

    customer = get_or_404(db, Customer, customer_id, tenant.id, "Customer not found")

    existing = db.execute(
        select(_User).where(_User.email == data.email)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="En bruker med denne e-posten finnes allerede")

    user = _User(
        tenant_id=tenant.id,
        email=data.email.lower(),
        password_hash=get_password_hash(data.initial_password),
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        role=_UserRole.CUSTOMER_PORTAL,
        customer_id=customer.id,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="user",
        entity_id=user.id,
        action=AuditAction.CREATE,
        new_values={"role": "customer_portal", "customer_id": customer.id, "email": user.email},
    ))
    db.commit()

    return PortalUserResponse(
        id=user.id, email=user.email, first_name=user.first_name,
        last_name=user.last_name, customer_id=user.customer_id, is_active=user.is_active,
    )


class PortalPasswordReset(BaseModel):
    new_password: Optional[str] = Field(
        None, min_length=8, max_length=128,
        description="Nytt passord. Hvis utelatt, genereres et tilfeldig passord."
    )


class PortalPasswordResetResponse(BaseModel):
    user_id: int
    email: str
    new_password: str  # Returneres KUN denne ene gangen \u2014 admin maa videreformidle


@router.post("/{customer_id}/portal-users/{user_id}/reset-password", response_model=PortalPasswordResetResponse)
async def reset_portal_user_password(
    customer_id: int,
    user_id: int,
    data: PortalPasswordReset,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Sett nytt passord for en portal-bruker. Returnerer passordet \u00e9n gang."""
    import secrets, string
    from ..auth_models import User as _User, UserRole as _UserRole
    from ..auth import get_password_hash

    user = db.execute(
        select(_User).where(
            _User.id == user_id,
            _User.tenant_id == tenant.id,
            _User.customer_id == customer_id,
            _User.role == _UserRole.CUSTOMER_PORTAL,
            _User.is_deleted == False,
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Portal-bruker ikke funnet")

    if data.new_password:
        new_password = data.new_password
    else:
        # Generer et lett-leselig passord (12 tegn, ingen forvekslinger)
        alphabet = "abcdefghijkmnpqrstuvwxyz23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        new_password = "".join(secrets.choice(alphabet) for _ in range(12))

    user.password_hash = get_password_hash(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    db.add(AuditLog(
        tenant_id=tenant.id,
        entity_type="user",
        entity_id=user.id,
        action=AuditAction.UPDATE,
        new_values={"password_reset_by_admin": True},
    ))
    db.commit()

    return PortalPasswordResetResponse(
        user_id=user.id, email=user.email, new_password=new_password,
    )

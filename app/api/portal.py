"""
Customer Portal API.

Endepunkter for sluttkunder (rolle CUSTOMER_PORTAL) som logger inn for
\u00e5 se egne ordrer, legge inn nye bestillinger og se produkter med
sine kontraktspriser.

En portal-bruker er knyttet til \u00e9n Customer via User.customer_id.
Hvis kunden er en hovedkunde, kan brukeren ogs\u00e5 se / bestille
for alle sub_outlets (utsalg).

Cutoff (15:00 dagen f\u00f8r) gjelder ogs\u00e5 her \u2014 kunden kan ikke
endre l\u00e5ste ordrer.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_user
from ..auth_models import User, UserRole
from ..models import (
    Customer, Product, Order, OrderLine,
    OrderStatus, SyncStatus, MasterTemplate, AdminAlert,
    CustomerFavoriteProduct,
)
from ..schemas import OrderResponse
from .pricing import get_effective_price
from ..cutoff import is_order_locked
from ..services.order_numbering import allocate_order_no
from ..time_utils import today_oslo, is_past_cutoff, is_past_cutoff_tenant, earliest_delivery_date

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portal", tags=["Customer Portal"])


# =============================================================================
# Schemas
# =============================================================================

class PortalOutlet(BaseModel):
    id: int
    name: str
    company_name: Optional[str] = None
    street_address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    is_main: bool = False  # True for hovedkunden, False for utsalg

    model_config = ConfigDict(from_attributes=True)


class PortalMeResponse(BaseModel):
    user_id: int
    email: str
    full_name: str
    main_customer: PortalOutlet
    outlets: List[PortalOutlet]  # alle utsalg brukeren kan bestille for (inkludert hovedkunden)
    tenant_name: str


class PortalProduct(BaseModel):
    id: int
    name: str
    sku: Optional[str] = None
    unit: Optional[str] = None
    unit_price: Decimal  # ferdig prisberegnet for denne kunden
    vat_rate: Decimal
    description: Optional[str] = None
    is_favorite: bool = False
    production_days: int = 0


class PortalEarliestDeliveryResponse(BaseModel):
    earliest_date: date
    production_days: int
    reason: str


class PortalRestrictionInfo(BaseModel):
    customer_id: int
    restrict_to_favorites: bool


class PortalOrderLineCreate(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0, le=10000)
    notes: Optional[str] = Field(None, max_length=500)


class PortalOrderCreate(BaseModel):
    customer_id: int  # utsalg-id
    delivery_date: date
    reference: Optional[str] = Field(None, max_length=255)
    customer_notes: Optional[str] = Field(None, max_length=2000)
    lines: List[PortalOrderLineCreate]


class PortalOrderLineUpdate(BaseModel):
    line_id: int
    quantity: int = Field(..., ge=0, le=10000)  # 0 = fjern linje


class PortalOrderUpdate(BaseModel):
    customer_notes: Optional[str] = Field(None, max_length=2000)
    reference: Optional[str] = Field(None, max_length=255)
    lines: Optional[List[PortalOrderLineUpdate]] = None


# =============================================================================
# Auth helper
# =============================================================================

def get_portal_user(current_user: User = Depends(get_current_user)) -> User:
    """Krever at innlogget bruker er CUSTOMER_PORTAL og har customer_id satt."""
    if current_user.role != UserRole.CUSTOMER_PORTAL:
        raise HTTPException(status_code=403, detail="Kun for kundeportal-brukere")
    if not current_user.customer_id:
        raise HTTPException(status_code=403, detail="Bruker er ikke koblet til en kunde")
    return current_user


def get_accessible_customer_ids(db: Session, user: User) -> List[int]:
    """
    Returner alle customer-IDer denne portal-brukeren kan se / bestille for.

    - Hvis bruker peker p\u00e5 en hovedkunde: hovedkunden + alle sub_outlets
    - Hvis bruker peker p\u00e5 et utsalg: bare det utsalget
    """
    main = db.execute(
        select(Customer).where(
            Customer.id == user.customer_id,
            Customer.tenant_id == user.tenant_id,
            Customer.is_deleted == False,
        ).options(selectinload(Customer.sub_outlets))
    ).scalar_one_or_none()
    if not main:
        raise HTTPException(status_code=404, detail="Kobling til kunde mangler")

    ids = [main.id]
    # Bare ekspander hvis dette ER en hovedkunde (parent_customer_id is None)
    if main.parent_customer_id is None:
        ids.extend(o.id for o in main.sub_outlets if not o.is_deleted)
    return ids


def _get_favorite_owner_id(db: Session, user: User, customer_id: int) -> int:
    """
    Returner customer_id som FAVORITT-listen og restrict-flagget skal hentes fra.

    Et utsalg arver hovedkundens favorittliste/innstilling. Hvis customer_id
    er en hovedkunde, returneres den selv.
    """
    cust = db.get(Customer, customer_id)
    if not cust or cust.tenant_id != user.tenant_id:
        return customer_id
    if cust.parent_customer_id is not None:
        return cust.parent_customer_id
    return customer_id


def _is_restricted_to_favorites(db: Session, user: User, customer_id: int) -> bool:
    owner_id = _get_favorite_owner_id(db, user, customer_id)
    cust = db.get(Customer, owner_id)
    return bool(cust and cust.restrict_to_favorites)


def _favorite_product_ids(db: Session, user: User, customer_id: int) -> set[int]:
    owner_id = _get_favorite_owner_id(db, user, customer_id)
    rows = db.execute(
        select(CustomerFavoriteProduct.product_id).where(
            CustomerFavoriteProduct.tenant_id == user.tenant_id,
            CustomerFavoriteProduct.customer_id == owner_id,
        )
    ).scalars().all()
    return set(rows)


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/me", response_model=PortalMeResponse)
def get_me(
    user: User = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    main = db.execute(
        select(Customer).where(Customer.id == user.customer_id)
        .options(selectinload(Customer.sub_outlets))
    ).scalar_one_or_none()
    if not main:
        raise HTTPException(status_code=404, detail="Kunde ikke funnet")

    outlets: List[PortalOutlet] = [PortalOutlet(
        id=main.id, name=main.name, company_name=main.company_name,
        street_address=main.street_address, postal_code=main.postal_code,
        city=main.city, is_main=True,
    )]
    if main.parent_customer_id is None:
        for sub in main.sub_outlets:
            if sub.is_deleted:
                continue
            outlets.append(PortalOutlet(
                id=sub.id, name=sub.name, company_name=sub.company_name,
                street_address=sub.street_address, postal_code=sub.postal_code,
                city=sub.city, is_main=False,
            ))

    tenant_name = user.tenant.name if user.tenant else ""

    return PortalMeResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        main_customer=outlets[0],
        outlets=outlets,
        tenant_name=tenant_name,
    )


@router.get("/favorites", response_model=List[PortalProduct])
def list_portal_favorites(
    customer_id: int,
    user: User = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """Lister favoritter for valgt utsalg, med effektiv pris.

    Favoritter arves fra hovedkunden hvis kunden er et utsalg.
    """
    allowed = get_accessible_customer_ids(db, user)
    if customer_id not in allowed:
        raise HTTPException(status_code=403, detail="Ingen tilgang til dette utsalget")

    fav_owner_id = _get_favorite_owner_id(db, user, customer_id)

    favs = db.execute(
        select(CustomerFavoriteProduct)
        .where(
            CustomerFavoriteProduct.tenant_id == user.tenant_id,
            CustomerFavoriteProduct.customer_id == fav_owner_id,
        )
        .options(selectinload(CustomerFavoriteProduct.product))
        .order_by(CustomerFavoriteProduct.sort_order.asc(), CustomerFavoriteProduct.id.asc())
    ).scalars().all()

    out: List[PortalProduct] = []
    today = today_oslo()
    for f in favs:
        p = f.product
        if not p or not p.is_active or p.is_deleted:
            continue
        try:
            price, _, _ = get_effective_price(db, customer_id, p.id, today, tenant_id=user.tenant_id)
        except Exception:
            price = p.default_price
        out.append(PortalProduct(
            id=p.id, name=p.name, sku=p.sku, unit=p.unit,
            unit_price=price, vat_rate=p.vat_rate,
            description=p.description,
            is_favorite=True,
            production_days=p.production_days or 0,
        ))
    return out


@router.get("/earliest-delivery", response_model=PortalEarliestDeliveryResponse)
def get_earliest_delivery(
    product_ids: Optional[str] = None,
    user: User = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """Returner tidligst mulig leveringsdato gitt valgte produkter (komma-separert id-liste).

    Tar høyde for tenant.cutoff, non_delivery_weekdays og max(production_days) over varene.
    """
    tenant_settings = (user.tenant.settings or {}) if user.tenant else {}
    max_prod_days = 0
    if product_ids:
        try:
            ids = [int(x) for x in product_ids.split(",") if x.strip()]
        except ValueError:
            ids = []
        if ids:
            rows = db.execute(
                select(Product.production_days).where(
                    Product.tenant_id == user.tenant_id,
                    Product.id.in_(ids),
                )
            ).all()
            max_prod_days = max((r[0] or 0 for r in rows), default=0)
    earliest = earliest_delivery_date(tenant_settings, production_days=max_prod_days)
    return PortalEarliestDeliveryResponse(
        earliest_date=earliest,
        production_days=max_prod_days,
        reason=(
            f"Inkluderer cutoff og {max_prod_days} produksjonsdag(er)."
            if max_prod_days else
            "Basert på cutoff og bakeriets ikke-leveringsdager."
        ),
    )


@router.get("/restrictions", response_model=PortalRestrictionInfo)
def get_portal_restrictions(
    customer_id: int,
    user: User = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """Returner om utsalget er begrenset til kun å bestille fra favorittlisten."""
    allowed = get_accessible_customer_ids(db, user)
    if customer_id not in allowed:
        raise HTTPException(status_code=403, detail="Ingen tilgang til dette utsalget")
    return PortalRestrictionInfo(
        customer_id=customer_id,
        restrict_to_favorites=_is_restricted_to_favorites(db, user, customer_id),
    )


@router.get("/products", response_model=List[PortalProduct])
def list_products(
    customer_id: int,
    user: User = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """Lister aktive produkter med effektiv pris for valgt utsalg.

    Markerer hvilke som er i kundens favorittliste (is_favorite=True).
    """
    allowed = get_accessible_customer_ids(db, user)
    if customer_id not in allowed:
        raise HTTPException(status_code=403, detail="Ingen tilgang til dette utsalget")

    # Favorittlisten kommer fra hovedkunden hvis denne kunden er et utsalg
    fav_customer_id = _get_favorite_owner_id(db, user, customer_id)
    fav_product_ids = set(db.execute(
        select(CustomerFavoriteProduct.product_id).where(
            CustomerFavoriteProduct.tenant_id == user.tenant_id,
            CustomerFavoriteProduct.customer_id == fav_customer_id,
        )
    ).scalars().all())

    products = db.execute(
        select(Product).where(
            Product.tenant_id == user.tenant_id,
            Product.is_active == True,
            Product.is_deleted == False,
        ).order_by(Product.name)
    ).scalars().all()

    out: List[PortalProduct] = []
    today = today_oslo()
    for p in products:
        try:
            price, _, _ = get_effective_price(db, customer_id, p.id, today, tenant_id=user.tenant_id)
        except Exception:
            price = p.default_price
        out.append(PortalProduct(
            id=p.id, name=p.name, sku=p.sku, unit=p.unit,
            unit_price=price, vat_rate=p.vat_rate,
            description=p.description,
            is_favorite=p.id in fav_product_ids,
            production_days=p.production_days or 0,
        ))
    return out


@router.get("/orders", response_model=List[OrderResponse])
def list_orders(
    customer_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    user: User = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """Liste over ordrer for kundens utsalg. Default: neste 30 dager."""
    allowed = get_accessible_customer_ids(db, user)
    if customer_id and customer_id not in allowed:
        raise HTTPException(status_code=403, detail="Ingen tilgang til dette utsalget")

    if from_date is None:
        from_date = today_oslo() - timedelta(days=7)
    if to_date is None:
        to_date = today_oslo() + timedelta(days=60)

    target_ids = [customer_id] if customer_id else allowed

    orders = db.execute(
        select(Order).where(
            Order.tenant_id == user.tenant_id,
            Order.customer_id.in_(target_ids),
            Order.is_deleted == False,
            Order.delivery_date >= from_date,
            Order.delivery_date <= to_date,
        )
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
        .order_by(Order.delivery_date.asc(), Order.id.asc())
    ).scalars().all()

    out = []
    for o in orders:
        data = OrderResponse.model_validate(o).model_dump()
        data["customer_name"] = o.customer.name if o.customer else None
        out.append(data)
    return out


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_portal_order(
    data: PortalOrderCreate,
    user: User = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    allowed = get_accessible_customer_ids(db, user)
    if data.customer_id not in allowed:
        raise HTTPException(status_code=403, detail="Ingen tilgang til dette utsalget")
    if data.delivery_date < today_oslo():
        raise HTTPException(status_code=400, detail="Leveringsdato kan ikke v\u00e6re i fortiden")
    if not data.lines:
        raise HTTPException(status_code=400, detail="Bestillingen m\u00e5 ha minst \u00e9n linje")

    customer = db.get(Customer, data.customer_id)
    if not customer or customer.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Utsalg ikke funnet")

    # Håndhev begrensning til favorittliste hvis satt på (hoved-)kunden
    if _is_restricted_to_favorites(db, user, data.customer_id):
        allowed_product_ids = _favorite_product_ids(db, user, data.customer_id)
        invalid = [l.product_id for l in data.lines if l.product_id not in allowed_product_ids]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Bestillingen inneholder produkter som ikke er i favorittlisten din. "
                    f"Ikke-tillatte produkt-IDer: {invalid}. Ta kontakt med bakeriet for å bestille andre varer."
                ),
            )

    # Sjekk cutoff: en ordre for i morgen kan ikke opprettes etter cutoff i dag
    tenant_settings = (user.tenant.settings or {}) if user.tenant else {}
    if is_past_cutoff_tenant(data.delivery_date, tenant_settings):
        raise HTTPException(
            status_code=400,
            detail="Bestillingsfristen for denne datoen har passert. Ta kontakt med bakeriet."
        )

    # Sjekk produksjonsdager: max(production_days) på tvers av varene må være tilfredsstilt
    product_ids = [l.product_id for l in data.lines]
    prod_days_rows = db.execute(
        select(Product.id, Product.production_days).where(
            Product.tenant_id == user.tenant_id,
            Product.id.in_(product_ids),
        )
    ).all()
    max_prod_days = max((row.production_days or 0 for row in prod_days_rows), default=0)
    earliest = earliest_delivery_date(tenant_settings, production_days=max_prod_days)
    if data.delivery_date < earliest:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tidligst mulig leveringsdato for denne ordren er {earliest.isoformat()} "
                f"({max_prod_days} produksjonsdag(er) kreves)."
            ),
        )

    tenant = user.tenant

    order = Order(
        tenant_id=user.tenant_id,
        customer_id=data.customer_id,
        delivery_date=data.delivery_date,
        reference=data.reference,
        customer_notes=data.customer_notes,
        status=OrderStatus.CONFIRMED,
        sync_status=SyncStatus.PENDING,
        is_adhoc_modified=True,  # opprettet manuelt fra kunde
        needs_review=True,  # portal-ordre venter på admin-godkjenning
        total_amount_excl_vat=Decimal("0"),
        total_vat=Decimal("0"),
        total_amount_incl_vat=Decimal("0"),
    )
    allocate_order_no(db, tenant, order)
    db.add(order)
    db.flush()

    excl_total = Decimal("0")
    vat_total = Decimal("0")
    incl_total = Decimal("0")
    for line in data.lines:
        product = db.get(Product, line.product_id)
        if not product or product.tenant_id != user.tenant_id or not product.is_active:
            raise HTTPException(status_code=400, detail=f"Produkt {line.product_id} er ikke tilgjengelig")
        try:
            unit_price, _, _ = get_effective_price(db, customer.id, product.id, data.delivery_date, tenant_id=user.tenant_id)
        except Exception:
            unit_price = product.default_price
        vat_rate = product.vat_rate
        excl = (Decimal(line.quantity) * unit_price).quantize(Decimal("0.01"))
        vat = (excl * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
        incl = (excl + vat).quantize(Decimal("0.01"))
        ol = OrderLine(
            tenant_id=user.tenant_id,
            order_id=order.id,
            product_id=product.id,
            quantity=line.quantity,
            unit_price=unit_price,
            vat_rate=vat_rate,
            line_amount_excl_vat=excl,
            line_vat=vat,
            line_amount_incl_vat=incl,
            notes=line.notes,
            is_adhoc_quantity=True,
        )
        db.add(ol)
        excl_total += excl
        vat_total += vat
        incl_total += incl

    order.total_amount_excl_vat = excl_total
    order.total_vat = vat_total
    order.total_amount_incl_vat = incl_total

    # Opprett popup-varsel for administrator. Lagres i AdminAlert-tabellen
    # med alert_type='portal_order'. Frontend poller /api/v1/notifications.
    try:
        alert = AdminAlert(
            tenant_id=user.tenant_id,
            alert_type="portal_order",
            severity="info",
            title=f"Ny portal-ordre fra {customer.name}",
            message=(
                f"Bestilling på {len(data.lines)} varelinje(r), "
                f"totalt {incl_total:.2f} kr inkl. mva, "
                f"levering {data.delivery_date.isoformat()}."
            ),
            related_entity_type="order",
            related_entity_id=order.id,
        )
        db.add(alert)
    except Exception as exc:  # pragma: no cover
        logger.warning("Klarte ikke å opprette portal-ordre-varsel: %s", exc)

    db.commit()
    db.refresh(order)

    # Last full
    full = db.execute(
        select(Order).where(Order.id == order.id)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
    ).scalar_one()
    data_out = OrderResponse.model_validate(full).model_dump()
    data_out["customer_name"] = full.customer.name if full.customer else None
    return data_out


@router.patch("/orders/{order_id}", response_model=OrderResponse)
def update_portal_order(
    order_id: int,
    data: PortalOrderUpdate,
    user: User = Depends(get_portal_user),
    db: Session = Depends(get_db),
):
    """
    Endre en eksisterende ordre. Kun mulig f\u00f8r cutoff.
    Linjer: send liste med {line_id, quantity}. quantity=0 sletter linjen.
    """
    allowed = get_accessible_customer_ids(db, user)

    order = db.execute(
        select(Order).where(
            Order.id == order_id,
            Order.tenant_id == user.tenant_id,
            Order.is_deleted == False,
        ).options(selectinload(Order.lines).selectinload(OrderLine.product))
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Ordre ikke funnet")
    if order.customer_id not in allowed:
        raise HTTPException(status_code=403, detail="Ingen tilgang")
    if is_order_locked(order):
        raise HTTPException(status_code=400, detail="Ordren er l\u00e5st og kan ikke endres")

    if data.customer_notes is not None:
        order.customer_notes = data.customer_notes
    if data.reference is not None:
        order.reference = data.reference

    if data.lines:
        line_map = {l.id: l for l in order.lines}
        for upd in data.lines:
            ol = line_map.get(upd.line_id)
            if not ol:
                continue
            if upd.quantity == 0:
                db.delete(ol)
            elif upd.quantity != ol.quantity:
                ol.quantity = upd.quantity
                excl = (Decimal(upd.quantity) * ol.unit_price).quantize(Decimal("0.01"))
                vat = (excl * ol.vat_rate / Decimal("100")).quantize(Decimal("0.01"))
                ol.line_amount_excl_vat = excl
                ol.line_vat = vat
                ol.line_amount_incl_vat = (excl + vat).quantize(Decimal("0.01"))
                ol.is_adhoc_quantity = True
        db.flush()
        db.refresh(order)
        order.total_amount_excl_vat = sum((l.line_amount_excl_vat for l in order.lines), Decimal("0"))
        order.total_vat = sum((l.line_vat for l in order.lines), Decimal("0"))
        order.total_amount_incl_vat = sum((l.line_amount_incl_vat for l in order.lines), Decimal("0"))
        order.is_adhoc_modified = True

    db.commit()
    db.refresh(order)

    full = db.execute(
        select(Order).where(Order.id == order.id)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product),
        )
    ).scalar_one()
    data_out = OrderResponse.model_validate(full).model_dump()
    data_out["customer_name"] = full.customer.name if full.customer else None
    return data_out

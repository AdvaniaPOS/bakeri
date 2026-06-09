"""
SQLAlchemy models for Lampeland Bakeri Ordresystem.

MULTI-TENANT ARCHITECTURE:
All business entities are scoped to a tenant (bakery chain).
Each tenant has isolated data that cannot be accessed by other tenants.

Core entities:
- Customer & Product: Mirrored from SuSoft POS (tenant-scoped)
- CustomerProductPrice: Customer-specific pricing with effective_from_date
- MasterTemplate: 7-day order template per customer
- Order: Actual orders with SuSoft sync state
- Supporting: Holidays, Audit logs, Route planning
"""
from datetime import datetime, date, time
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional, List, TYPE_CHECKING
import uuid as uuid_module

from sqlalchemy import (
    String, Integer, Numeric, Boolean, DateTime, Date, Time, Text,
    ForeignKey, Enum, CheckConstraint, Index, UniqueConstraint, JSON,
    TypeDecorator, CHAR
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, declared_attr
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from .database import Base

if TYPE_CHECKING:
    from .auth_models import Tenant


# Portable UUID type that works with both PostgreSQL and SQLite
class GUID(TypeDecorator):
    """Platform-independent GUID type."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return value
        else:
            return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid_module.UUID):
                return uuid_module.UUID(value)
            return value


# =============================================================================
# ENUMS
# =============================================================================

class SyncStatus(str, PyEnum):
    """SuSoft synchronization status."""
    PENDING = "pending"           # Not yet sent to SuSoft
    SYNCED = "synced"             # Successfully synced with SuSoft
    FAILED = "failed"             # Sync failed, needs retry
    RETRY_SCHEDULED = "retry_scheduled"  # Retry scheduled
    CANCELLED = "cancelled"       # Cancelled locally, needs SuSoft update
    

class OrderStatus(str, PyEnum):
    """Order lifecycle status."""
    DRAFT = "draft"               # Template-generated, not yet active
    CONFIRMED = "confirmed"       # Confirmed by admin
    READY_FOR_DELIVERY = "ready_for_delivery"  # Sent to SuSoft
    IN_TRANSIT = "in_transit"     # Driver has started delivery
    DELIVERED = "delivered"       # Confirmed delivered
    CANCELLED = "cancelled"       # Order cancelled


class DayOfWeek(int, PyEnum):
    """Day of week (ISO standard: Monday=1, Sunday=7)."""
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


class DeliveryIssueType(str, PyEnum):
    """Types of delivery issues drivers can report."""
    DAMAGED = "damaged"
    MISSING = "missing"
    WRONG_PRODUCT = "wrong_product"
    CUSTOMER_REFUSED = "customer_refused"
    ADDRESS_NOT_FOUND = "address_not_found"
    OTHER = "other"


class AuditAction(str, PyEnum):
    """Types of auditable actions."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    CANCEL = "cancel"
    SYNC = "sync"
    PRICE_CHANGE = "price_change"
    PANIC_CANCEL = "panic_cancel"


class VatClass(str, PyEnum):
    """
    MVA-klasse iht. norsk regelverk.

    SuSoft er master for fakturering, men ordresystemet trenger satsen
    for å vise korrekte estimater i UI.
    """
    FOOD_15 = "food_15"           # Mat: 15% MVA (standard for bakeri)
    STANDARD_25 = "standard_25"   # Standard varer/tjenester: 25%
    REDUCED_12 = "reduced_12"     # Redusert: 12% (transport, overnatting m.m.)
    ZERO = "zero"                 # 0% (eksport, visse tjenester)


VAT_CLASS_RATES: dict[VatClass, Decimal] = {
    VatClass.FOOD_15: Decimal("15.00"),
    VatClass.STANDARD_25: Decimal("25.00"),
    VatClass.REDUCED_12: Decimal("12.00"),
    VatClass.ZERO: Decimal("0.00"),
}


# =============================================================================
# MIXIN CLASSES
# =============================================================================

class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class SoftDeleteMixin:
    """Mixin for soft delete functionality."""
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deletion_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class TenantMixin:
    """
    Mixin for multi-tenant entities.
    
    All entities that are scoped to a specific tenant (bakery chain)
    should inherit from this mixin. It adds:
    - tenant_id foreign key
    - Automatic filtering in queries (via API dependencies)
    """
    @declared_attr
    def tenant_id(cls) -> Mapped[int]:
        return mapped_column(
            Integer, 
            ForeignKey("tenants.id", ondelete="CASCADE"), 
            nullable=False, 
            index=True,
            comment="Tenant (bakery chain) this entity belongs to"
        )


# =============================================================================
# ROUTE MODEL (Delivery Routes)
# =============================================================================

class Route(Base, TimestampMixin, TenantMixin):
    """
    Leveringsrute for gruppering av kunder.
    
    Eksempel: "Rute 1 - Kongsberg" inneholder alle kunder i Kongsberg-området.
    Kunder tildeles en rute manuelt av admin.
    
    TENANT-SCOPED: Each tenant has their own routes.
    """
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Rutenavn, f.eks. 'Rute 1 - Kongsberg'"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Leveringsdager for denne ruten (JSON array: [1,2,3,4,5] = Man-Fre)
    delivery_days: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=lambda: [1, 2, 3, 4, 5],
        comment="Liste av ISO ukedager [1,2,3,4,5] = Man-Fre"
    )
    
    # Standard starttid for leveringer på denne ruten
    default_start_time: Mapped[Optional[time]] = mapped_column(
        Time, nullable=True, default=time(7, 0),
        comment="Når sjåføren normalt starter denne ruten"
    )
    
    # Aktiv status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Posisjon i rekkefølgen (for manuell sortering)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Relationships
    customers: Mapped[List["Customer"]] = relationship(back_populates="route")
    postal_rules: Mapped[List["RoutePostalRule"]] = relationship(
        back_populates="route", cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        # Route name unique within tenant
        UniqueConstraint("tenant_id", "name", name="uq_route_tenant_name"),
        Index("ix_routes_tenant_active", "tenant_id", "is_active", "sort_order"),
    )


class RoutePostalRule(Base, TimestampMixin, TenantMixin):
    """
    Postnummer-serie som tilhoerer en rute.
    En rute kan ha flere serier; en kunde matcher hvis postnummer ligger
    innenfor minst en serie. For enkelt-postnummer settes from_code = to_code.
    """
    __tablename__ = "route_postal_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_code: Mapped[str] = mapped_column(String(10), nullable=False, comment="Fra-postnummer (inklusiv)")
    to_code: Mapped[str] = mapped_column(String(10), nullable=False, comment="Til-postnummer (inklusiv)")
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="Valgfri etikett, f.eks. 'Sentrum'")

    route: Mapped["Route"] = relationship(back_populates="postal_rules")

    __table_args__ = (
        Index("ix_route_postal_rules_tenant_route", "tenant_id", "route_id"),
        CheckConstraint("from_code <= to_code", name="ck_postal_rule_from_le_to"),
    )


# =============================================================================
# CUSTOMER MODEL
# =============================================================================

class Customer(Base, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """
    Customer entity - mirrored from SuSoft POS.
    
    TENANT-SCOPED: Each tenant has their own customers.
    
    Supports:
    - SuSoft sync tracking
    - Customer-specific delivery windows
    - Configurable order generation lead time
    """
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # SuSoft integration
    susoft_customer_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Customer ID in SuSoft POS system"
    )
    susoft_last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Address
    street_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="Norway", nullable=False)
    
    # Geolocation for route optimization
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6), nullable=True)
    
    # Delivery preferences
    delivery_window_start: Mapped[Optional[time]] = mapped_column(
        Time, nullable=True, comment="Earliest delivery time"
    )
    delivery_window_end: Mapped[Optional[time]] = mapped_column(
        Time, nullable=True, comment="Latest delivery time"
    )
    delivery_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Order generation settings
    order_lead_days: Mapped[int] = mapped_column(
        Integer, default=14, nullable=False,
        comment="Days in advance to generate orders (7-84 days = 1-12 weeks)"
    )

    # Helligdagslevering
    delivers_on_holidays: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment=(
            "Skal det leveres til denne kunden på helligdager? "
            "True for kunder som hoteller, sykehus, sykehjem som trenger brød "
            "også på røde dager."
        )
    )

    # Portal: begrens kunden til kun å bestille fra sin favorittliste.
    # Hvis False (default) kan kunden også søke opp og bestille andre varer.
    restrict_to_favorites: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false",
        comment="Hvis True kan portal-kunden kun bestille produkter som finnes i favorittlisten."
    )

    # Customer state
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Route assignment
    route_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("routes.id", ondelete="SET NULL"), 
        nullable=True, index=True,
        comment="Assigned delivery route"
    )

    # Multi-utsalg / kjedekunder: en kunde kan være et utsalg under en hovedkunde.
    # Hovedkundens portal-bruker ser ordrer for ALLE utsalg under seg.
    # Et utsalg som har egen portal-bruker ser KUN sine egne ordrer.
    parent_customer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Hvis satt: denne kunden er et utsalg under hovedkunden med denne IDen."
    )

    # Relationships
    route: Mapped[Optional["Route"]] = relationship(back_populates="customers")
    parent_customer: Mapped[Optional["Customer"]] = relationship(
        "Customer", remote_side="Customer.id", back_populates="sub_outlets",
        foreign_keys=[parent_customer_id]
    )
    sub_outlets: Mapped[List["Customer"]] = relationship(
        "Customer", back_populates="parent_customer",
        foreign_keys=[parent_customer_id]
    )
    custom_prices: Mapped[List["CustomerProductPrice"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    favorite_products: Mapped[List["CustomerFavoriteProduct"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan",
        order_by="CustomerFavoriteProduct.sort_order"
    )
    master_templates: Mapped[List["MasterTemplate"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    orders: Mapped[List["Order"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    blocked_dates: Mapped[List["CustomerBlockedDate"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        # SuSoft customer ID unique within tenant
        UniqueConstraint("tenant_id", "susoft_customer_id", name="uq_customer_tenant_susoft"),
        CheckConstraint("order_lead_days >= 7 AND order_lead_days <= 84",
                        name="check_order_lead_days_range"),
        Index("ix_customers_tenant_active", "tenant_id", "is_active"),
    )


# =============================================================================
# PRODUCT MODEL
# =============================================================================

class Product(Base, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """
    Product entity - mirrored from SuSoft POS.
    
    TENANT-SCOPED: Each tenant has their own product catalog.
    
    Contains default pricing; customer-specific prices in CustomerProductPrice.
    """
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # SuSoft integration
    susoft_product_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Product ID in SuSoft POS system"
    )
    susoft_last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Product info
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    
    # Default pricing (can be overridden per customer)
    default_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False,
        comment="Default price in NOK, before customer-specific overrides"
    )
    unit: Mapped[str] = mapped_column(
        String(20), default="stk", nullable=False,
        comment="Unit of measurement (stk, kg, etc.)"
    )
    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("15.00"), nullable=False,
        comment="VAT rate percentage (food typically 15% in Norway)"
    )
    vat_class: Mapped[VatClass] = mapped_column(
        Enum(VatClass), default=VatClass.FOOD_15, nullable=False,
        comment=(
            "MVA-klasse. Hovedsakelig FOOD_15 for bakerivarer. "
            "Brukes for visning i UI; SuSoft er master for fakturering."
        )
    )

    # Product state
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active_overridden: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false",
        comment="Hvis True, skal Susoft-sync IKKE overskrive is_active (lokal styring vinner)"
    )
    is_available_for_order: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Stock tracking (optional)
    min_order_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Produksjonsplanlegging (batch-runding + ovns-/stasjons-gruppering)
    batch_size: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, server_default="1",
        comment="Standard batch-størrelse for baking. Bestilt antall rundes opp til nærmeste batch."
    )
    production_step: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Produksjons-steg/stasjon (f.eks. 'Ovn 1', 'Bakebenk', 'Stekeovn'). Brukes til gruppering i produksjonsplan."
    )
    production_lead_minutes: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0",
        comment="Estimert tid pr. batch i minutter (heving + steking)."
    )
    production_days: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0",
        comment="Antall produksjonsdager varen krever (øker minimum levering med dette antall produksjonsdager)."
    )

    # Allergener (komma-separert liste, synces fra SuSoft, kan overstyres lokalt)
    allergens: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="Komma-separert liste med allergener (f.eks. 'Hvete, Egg, Melk'). Hentes fra SuSoft."
    )

    # Relationships
    custom_prices: Mapped[List["CustomerProductPrice"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    favorited_by: Mapped[List["CustomerFavoriteProduct"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        # SKU and SuSoft ID unique within tenant
        UniqueConstraint("tenant_id", "sku", name="uq_product_tenant_sku"),
        UniqueConstraint("tenant_id", "susoft_product_id", name="uq_product_tenant_susoft"),
        Index("ix_products_tenant_active_available", "tenant_id", "is_active", "is_available_for_order"),
    )


# =============================================================================
# CUSTOMER PRODUCT PRICE - The Price-Date Logic
# =============================================================================

class CustomerProductPrice(Base, TimestampMixin, TenantMixin):
    """
    Customer-specific product pricing with scheduled price changes.
    
    TENANT-SCOPED: Prices are per tenant.
    
    KEY FEATURES:
    - effective_from_date: Price becomes active from this date
    - Multiple future prices can be scheduled
    - Query: Find price for (customer, product, date) by getting the 
             most recent effective_from_date <= target_date
    - When price changes, system must update ALL affected orders in DB
      AND trigger SuSoft API updates for orders already sent
    """
    __tablename__ = "customer_product_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    
    # Price with effective date
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False,
        comment="Customer-specific price in NOK"
    )
    effective_from_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="Date from which this price becomes effective"
    )
    effective_to_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True,
        comment="Optional end date (auto-calculated from next price entry)"
    )
    
    # Who made the change
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Sync tracking for price propagation
    orders_updated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Have all affected orders been updated with this price?"
    )
    susoft_sync_triggered: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Has SuSoft been notified of affected order price changes?"
    )
    
    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="custom_prices")
    product: Mapped["Product"] = relationship(back_populates="custom_prices")
    
    __table_args__ = (
        # Unique constraint: one price per customer/product/effective_date
        UniqueConstraint("customer_id", "product_id", "effective_from_date", 
                         name="uq_customer_product_price_date"),
        # Index for efficient price lookup (DESC på dato for raskest oppslag)
        Index("ix_customer_product_price_lookup", 
              "customer_id", "product_id", "effective_from_date"),
        # Indeks for å finne pris-perioder som dekker en gitt dato (effective_to_date != NULL)
        Index("ix_customer_product_price_history",
              "customer_id", "product_id", "effective_from_date", "effective_to_date"),
    )


# =============================================================================
# CUSTOMER FAVORITE PRODUCT - Kundens kuraterte favorittliste i portalen
# =============================================================================

class CustomerFavoriteProduct(Base, TimestampMixin, TenantMixin):
    """
    Kuratert favorittliste pr. kunde. Vises øverst i portalens bestillingsside.

    Hvis Customer.restrict_to_favorites = True, kan kunden kun bestille
    produkter som finnes i denne listen. Spesialpriser pr. kunde-vare lagres
    fortsatt i CustomerProductPrice (favorittlisten styrer kun hva som vises).
    """
    __tablename__ = "customer_favorite_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0",
        comment="Lavere tall vises først i portalen.",
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="favorite_products")
    product: Mapped["Product"] = relationship(back_populates="favorited_by")

    __table_args__ = (
        UniqueConstraint("customer_id", "product_id", name="uq_customer_favorite_product"),
        Index("ix_customer_favorite_sort", "customer_id", "sort_order"),
    )


# =============================================================================
# MASTER TEMPLATE - The Order Matrix
# =============================================================================

class MasterTemplate(Base, TimestampMixin, TenantMixin):
    """
    Master order template for a customer.
    
    TENANT-SCOPED: Templates are per tenant.
    
    Each customer has one active template containing a 7-day grid
    where specific product quantities are set per day of week.
    """
    __tablename__ = "master_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), 
        nullable=False, index=True
    )
    
    name: Mapped[str] = mapped_column(
        String(255), default="Standard Ukentlig Ordre", nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Standard referanse som kopieres til alle ordrer generert fra denne malen.
    default_reference: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Settes paa malen, kopieres til Order.reference ved generering"
    )
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Track when template was last used to generate orders
    last_generated_for_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True,
        comment="Last delivery date for which orders were generated"
    )
    
    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="master_templates")
    items: Mapped[List["MasterTemplateItem"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        # Only one active template per customer per tenant
        Index("ix_master_template_tenant_active", "tenant_id", "customer_id", "is_active"),
    )


class MasterTemplateItem(Base, TimestampMixin, TenantMixin):
    """
    Individual line item in a master template.
    
    TENANT-SCOPED: Template items are per tenant.
    
    Represents: "On [day_of_week], deliver [quantity] of [product]"
    """
    __tablename__ = "master_template_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("master_templates.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    
    day_of_week: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="ISO day of week: 1=Monday, 7=Sunday"
    )
    quantity: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Quantity to deliver on this day"
    )
    
    # Optional notes for this specific product/day combo
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Relationships
    template: Mapped["MasterTemplate"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()
    
    __table_args__ = (
        CheckConstraint("day_of_week >= 1 AND day_of_week <= 7", 
                        name="check_day_of_week_range"),
        CheckConstraint("quantity >= 0", name="check_quantity_positive"),
        # Unique: one entry per template/product/day
        UniqueConstraint("template_id", "product_id", "day_of_week",
                         name="uq_template_product_day"),
        Index("ix_template_items_by_day", "template_id", "day_of_week"),
    )


# =============================================================================
# ORDER & ORDER LINES
# =============================================================================

class Order(Base, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """
    Actual order for a specific delivery date.
    
    TENANT-SCOPED: Orders are per tenant.
    
    GENERATION:
    - Auto-generated from MasterTemplate N days in advance (configurable per customer)
    - Can be ad-hoc modified without affecting the master template
    
    SYNC:
    - susoft_order_id tracks the order in SuSoft for updates/deletes
    - sync_status tracks synchronization state
    - Cut-off: Changes locked at 10:00 day before delivery
    """
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_uuid: Mapped[uuid_module.UUID] = mapped_column(
        GUID(), default=uuid_module.uuid4, unique=True, nullable=False
    )

    # Per-tenant lopenr — settes ved opprettelse, brukes til pen visning og PDF.
    # `order_no_display` er prefiks-aar-lopenr, f.eks. "LAM-2026-000123".
    order_no_seq: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True,
        comment="Sekvensielt ordrenr per tenant (1, 2, 3...). Tildeles ved opprettelse."
    )
    order_no_display: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True,
        comment="Pent formatert ordrenr (f.eks. 'LAM-2026-000123') vist i UI/PDF."
    )

    # Kundens referanse / PO-nummer / planreferanse — kopiert fra mal hvis fra MasterTemplate.
    reference: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Valgfri ekstern referanse (kundens PO, plan-navn, prosjekt). Vises pa PDF."
    )
    
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    
    # Delivery date
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    
    # Status tracking
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.DRAFT, nullable=False, index=True
    )
    
    # SuSoft integration
    susoft_order_id: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True, index=True,
        comment="Order ID in SuSoft POS - used for updates/deletes"
    )
    sync_status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus), default=SyncStatus.PENDING, nullable=False
    )
    last_sync_attempt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sync_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sync_retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment=(
            "Når neste sync-forsøk skal skje (eksponentiell backoff). "
            "NULL = ingen retry planlagt."
        )
    )
    sync_locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment=(
            "Soft-lock for å hindre at to workers prosesserer samme ordre samtidig. "
            "Settes når en worker plukker opp ordren, ryddes etter ferdig."
        )
    )

    # SuSoft invoice tracking (POST /invoice)
    susoft_invoice_no: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Faktura-nummer i SuSoft etter at ordren er fakturert (POST /invoice)."
    )
    invoiced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Tidspunkt da ordren ble fakturert i SuSoft."
    )

    # =====================================================================
    # SuSoft INGESTION (orders polled FROM SuSoft, opposite of /order POST)
    # Brukt av sync_orders_from_susoft hver 5. minutt.
    # =====================================================================
    susoft_uuid: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
        comment="SuSoft `uuid` for ordren — dedup-nøkkel ved polling."
    )
    susoft_order_no: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True,
        comment="SuSoft `orderNo` slik den vises i SuSoft-UIet."
    )
    susoft_shop_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True,
        comment="Shop-ID i SuSoft (kasse/utsalg) som ordren ble registrert på."
    )
    susoft_pickup_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Avtalt henting i SuSoft (`pickupDate`). Null hvis ikke pickup."
    )
    susoft_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Avtalt levering i SuSoft (`deliveryDate`). Null hvis ikke delivery."
    )
    susoft_fulfillment_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="`pickup` | `delivery` | `unknown` — utledet fra SuSoft-payload."
    )
    susoft_raw_payload: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="Rå SuSoft-rad fra siste polling — for debugging/audit."
    )
    susoft_admin_payload: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="Sist kjente FULLE admin-cart payload fra SuSoft (/admin/order/uuid). "
                "Brukes som basis for PUT-tilbake (to-veis sync) for å bevare alle "
                "felt vi ikke speiler lokalt."
    )
    susoft_payload_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="SHA256 av normaliserte sync-relevante felt fra SuSoft. "
                "Brukes til å detektere endringer i SuSoft mellom pull-runder."
    )
    susoft_pending_push: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
        comment="True når lokal endring venter på å pushes til SuSoft via PUT /admin/order/uuid."
    )
    susoft_last_push_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Sist vellykkede PUT-tilbake til SuSoft."
    )
    susoft_last_push_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Feilmelding fra siste mislykkede push (null ved suksess)."
    )
    source: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, index=True,
        comment="Hvor ordren kom fra: `template`, `portal`, `manual`, `susoft_import`."
    )

    # Order source
    generated_from_template_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("master_templates.id", ondelete="SET NULL"), nullable=True
    )
    is_adhoc_modified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Has this order been modified from the template?"
    )
    
    # Totals (calculated from lines)
    total_amount_excl_vat: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    total_vat: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    total_amount_incl_vat: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    
    # Cut-off tracking
    is_locked: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Locked after cut-off time (10:00 day before delivery)"
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Delivery tracking
    route_position: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Position in delivery route for optimized routing"
    )
    estimated_delivery_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    actual_delivery_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_photo_url: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True,
        comment="URL eller data-URL til bilde tatt ved levering (sjåfør-PWA)."
    )
    delivery_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Portal review flag — settes TRUE for ordrer opprettet fra kunde-portalen
    # som administrator bør se gjennom (godkjenne / korrigere) før de
    # eventuelt sendes til produksjon/SuSoft.
    needs_review: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
        comment="Ordre fra portal som venter på admin-godkjenning."
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Order notes
    internal_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    customer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="orders")
    generated_from_template: Mapped[Optional["MasterTemplate"]] = relationship()
    lines: Mapped[List["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    delivery_issues: Mapped[List["DeliveryIssue"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    amendments: Mapped[List["OrderAmendment"]] = relationship(
        back_populates="order", cascade="all, delete-orphan",
        order_by="OrderAmendment.amended_at"
    )
    
    __table_args__ = (
        # SuSoft order ID unique within tenant
        UniqueConstraint("tenant_id", "susoft_order_id", name="uq_order_tenant_susoft"),
        # SuSoft uuid (fra polling) unik innen tenant — dedup-nøkkel
        UniqueConstraint("tenant_id", "susoft_uuid", name="uq_order_tenant_susoft_uuid"),
        # Per-tenant lopenr unik (manuelt validert i kode siden NULL er tillatt for legacy)
        UniqueConstraint("tenant_id", "order_no_seq", name="uq_order_tenant_seq"),
        Index("ix_orders_tenant_delivery_status", "tenant_id", "delivery_date", "status"),
        Index("ix_orders_sync_pending", "sync_status"),
        # Indeks for sweep-task som finner ordrer som trenger nytt sync-forsøk
        Index("ix_orders_sync_retry", "sync_status", "next_retry_at"),
        # Indeks for daglig leveringsvisning + sync-status
        Index("ix_orders_delivery_date_sync", "delivery_date", "sync_status"),
    )


class OrderLine(Base, TimestampMixin, TenantMixin):
    """
    Individual line item in an order.
    
    TENANT-SCOPED: Order lines are per tenant.
    
    Price is captured at order creation but can be updated
    when CustomerProductPrice changes for future orders.
    """
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Price at time of order (for historical accuracy)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False,
        comment="Unit price used for this order"
    )
    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False,
        comment="VAT rate at time of order"
    )
    
    # Calculated totals
    line_amount_excl_vat: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    line_vat: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_amount_incl_vat: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    
    # Track if this line was modified from template
    is_adhoc_quantity: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Was quantity modified from template?"
    )
    original_template_quantity: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Original quantity from template (if modified)"
    )
    
    # Track price updates
    price_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="Last time price was updated due to price schedule change"
    )

    # Faktisk levert / svinn / retur
    delivered_quantity: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Antall faktisk levert (sjåfør tikker av). NULL hvis ikke registrert ennå."
    )
    waste_quantity: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0",
        comment="Svinn registrert for denne linjen (kastet/ikke solgt)."
    )
    return_quantity: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0",
        comment="Retur fra dagligvare (krediteres kunden)."
    )
    
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Relationships
    order: Mapped["Order"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship()
    
    __table_args__ = (
        CheckConstraint("quantity > 0", name="check_line_quantity_positive"),
        Index("ix_order_lines_order", "order_id"),
    )


# =============================================================================
# ORDER AMENDMENTS (endringslogg / avvik)
# =============================================================================

class OrderAmendment(Base, TimestampMixin, TenantMixin):
    """
    Endringslogg / avvik paa en ordre.

    Brukes for sporbarhet naar en ordre endres etter at den er bekreftet
    eller utlevert. Vises pa leveringsbekreftelsen som en revisjonshistorikk.

    Eksempel: Kunde ringer kl 14:00 og ber om 5 ekstra wraps. Operatoer
    registrerer en amendment med reason="Lagt til 5 wraps etter forespoersel"
    og evt. ny reference="PO-987".
    """
    __tablename__ = "order_amendments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amended_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    amended_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="User-id paa den som registrerte avviket. NULL = system."
    )
    amended_by_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Snapshotted navn pa person (i tilfelle bruker slettes)"
    )
    reason: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Beskrivelse av avvik / endring"
    )
    reference: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Ny referanse (oppdaterer Order.reference hvis satt)"
    )
    changes_summary: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Snapshot av hva som ble endret (fritekst eller JSON)"
    )

    order: Mapped["Order"] = relationship(back_populates="amendments")

    __table_args__ = (
        Index("ix_order_amendments_tenant_order", "tenant_id", "order_id"),
    )


# =============================================================================
# AD-HOC ORDER OVERRIDES
# =============================================================================

class OrderDateOverride(Base, TimestampMixin, TenantMixin):
    """
    Ad-hoc quantity override for a specific date.
    
    TENANT-SCOPED: Overrides are per tenant.
    
    Use case: Override template quantity for ONE specific date
    without modifying the master template.
    
    Example: "Extra 10 loaves on December 24th" or "Skip delivery on May 17th"
    """
    __tablename__ = "order_date_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    
    override_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Override quantity (0 = skip this product for this date)"
    )
    
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Was this override applied to the generated order?
    applied_to_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    
    __table_args__ = (
        UniqueConstraint("customer_id", "product_id", "override_date",
                         name="uq_override_customer_product_date"),
        Index("ix_overrides_by_date", "override_date"),
    )


# =============================================================================
# HOLIDAYS & BLOCKED DATES
# =============================================================================

class Holiday(Base, TimestampMixin, TenantMixin):
    """
    Norwegian public holidays.
    
    TENANT-SCOPED: Each tenant manages their own holiday calendar.
    
    Orders on these dates automatically have quantity = 0.
    """
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Is this a full closure or partial?
    is_full_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Year can be null for recurring holidays
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    __table_args__ = (
        # Holiday date unique within tenant
        UniqueConstraint("tenant_id", "holiday_date", name="uq_holiday_tenant_date"),
        Index("ix_holidays_tenant_date", "tenant_id", "holiday_date"),
    )


class CustomerBlockedDate(Base, TimestampMixin, TenantMixin):
    """
    Customer-specific blocked date ranges (e.g., summer holidays).
    
    TENANT-SCOPED: Blocked dates are per tenant.
    
    Admin can block custom date ranges per customer.
    """
    __tablename__ = "customer_blocked_dates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="blocked_dates")
    
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="check_date_range_valid"),
        Index("ix_blocked_dates_range", "customer_id", "start_date", "end_date"),
    )


# =============================================================================
# DELIVERY & DRIVER PORTAL
# =============================================================================

class DeliveryRoute(Base, TimestampMixin, TenantMixin):
    """
    Optimized delivery route for a specific date.
    
    TENANT-SCOPED: Delivery routes are per tenant.
    
    Generated using Google Maps API.
    """
    __tablename__ = "delivery_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    route_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    
    # Google Maps optimization data
    total_distance_km: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    total_duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    optimization_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Route as JSON (ordered list of stops with metadata)
    route_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Driver assignment
    assigned_driver_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    driver_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    driver_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # PDF generation
    pdf_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pdf_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    __table_args__ = (
        # Route date unique within tenant
        UniqueConstraint("tenant_id", "route_date", name="uq_delivery_route_tenant_date"),
        Index("ix_delivery_routes_tenant_date", "tenant_id", "route_date"),
    )


class DeliveryIssue(Base, TimestampMixin, TenantMixin):
    """
    Driver-reported delivery issues (discrepancy reporting).
    
    TENANT-SCOPED: Delivery issues are per tenant.
    
    Provides audit trail for problems.
    """
    __tablename__ = "delivery_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    
    issue_type: Mapped[DeliveryIssueType] = mapped_column(
        Enum(DeliveryIssueType), nullable=False
    )
    quantity_affected: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Who reported and when
    reported_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    
    # Resolution tracking
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    order: Mapped["Order"] = relationship(back_populates="delivery_issues")
    product: Mapped[Optional["Product"]] = relationship()


# =============================================================================
# AUDIT LOG
# =============================================================================

class AuditLog(Base, TenantMixin):
    """
    Audit trail for all significant actions.
    
    TENANT-SCOPED: Audit logs are per tenant.
    
    REQUIREMENTS:
    - Log all deletions with required reason (dropdown + text)
    - Include timestamp and user ID
    - Track price changes and their propagation
    - Log panic button batch operations
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # When and who
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # What was affected
    entity_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Table/model name (customer, order, product, etc.)"
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # The action
    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction), nullable=False)
    
    # Deletion tracking (required for deletes)
    deletion_reason_category: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Dropdown selection: duplicate, mistake, customer_request, etc."
    )
    deletion_reason_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Free-text explanation"
    )
    
    # Change details
    old_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    new_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Context
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    additional_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    __table_args__ = (
        Index("ix_audit_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_audit_tenant_user_time", "tenant_id", "user_id", "timestamp"),
        Index("ix_audit_tenant_action", "tenant_id", "action", "timestamp"),
    )


# =============================================================================
# SYNC TRACKING & ALERTS
# =============================================================================

class SyncLog(Base, TimestampMixin, TenantMixin):
    """
    Log of all SuSoft API sync attempts.
    
    TENANT-SCOPED: Sync logs are per tenant.
    
    Used for debugging and retry logic.
    """
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    sync_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Type: order_create, order_update, order_delete, customer_sync, etc."
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # API details
    http_method: Mapped[str] = mapped_column(String(10), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    request_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Response
    response_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Outcome
    was_successful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Retry tracking
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    __table_args__ = (
        Index("ix_sync_logs_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_sync_logs_pending_retry", "next_retry_at"),
    )


class ScheduledTaskRun(Base):
    """
    Logg over kj\u00f8ringer av Celery-beat tasks (cross-tenant).

    GLOBAL (ikke tenant-scoped): Brukes av SUPER_ADMIN for \u00e5 verifisere
    at periodiske oppgaver kj\u00f8rer som planlagt og se sammendrag av resultatet
    (antall ordrer generert, kunder behandlet, evt. feilmelding).
    """
    __tablename__ = "scheduled_task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    task_name: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
        comment="Celery task-navn, f.eks. 'app.tasks.generate_orders_for_all_customers'"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True,
        comment="N\u00e5r task-en startet (UTC, naive)"
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="N\u00e5r task-en var ferdig. NULL hvis fortsatt p\u00e5g\u00e5ende."
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Varighet i millisekunder."
    )
    success: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="True hvis task fullf\u00f8rte uten ubehandlet feil."
    )
    result: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="Sammendrag fra task-en (f.eks. {'orders_created': 5, 'customers_processed': 12})."
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Stack-trace eller feilmelding hvis success=False."
    )

    __table_args__ = (
        Index("ix_scheduled_task_runs_name_started", "task_name", "started_at"),
    )


class AdminAlert(Base, TimestampMixin, TenantMixin):
    """
    Alert notifications for administrators.
    
    TENANT-SCOPED: Alerts are per tenant.
    
    Triggered by sync failures, system issues, etc.
    """
    __tablename__ = "admin_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    alert_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="sync_failure, system_error, price_update_pending, etc."
    )
    severity: Mapped[str] = mapped_column(
        String(20), default="warning", nullable=False,
        comment="info, warning, error, critical"
    )
    
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Related entity
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    related_entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # State
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Email notification tracking
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    email_recipients: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    __table_args__ = (
        Index("ix_alerts_tenant_unread", "tenant_id", "is_read", "severity"),
    )


# =============================================================================
# USER / ADMIN - REMOVED (See auth_models.py for multi-tenant User model)
# =============================================================================
# The User model has been moved to auth_models.py with proper multi-tenant
# support, roles, and authentication features.


# =============================================================================
# DAILY PRODUCTION SUMMARY
# =============================================================================

class DailyProductionSummary(Base, TimestampMixin, TenantMixin):
    """
    Aggregert produksjonsrapport per dag.
    
    TENANT-SCOPED: Production summaries are per tenant.

    Genereres automatisk når ordrer låses (kl 10:00 dagen før).
    Brukes av bakerne for å vite hvor mye som skal produseres.
    """
    __tablename__ = "daily_production_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    production_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True,
        comment="Leveringsdato for denne produksjonen"
    )
    
    # Aggregerte produkttall som JSON
    # Format: [{"product_id": 1, "product_name": "Kneipp", "total_quantity": 450, "unit": "stk"}]
    product_totals: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="Aggregerte produktmengder"
    )
    
    # Metadata
    total_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_customers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_order_lines: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Status
    is_finalized: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Låst etter produksjon er startet"
    )
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finalized_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # PDF generering
    pdf_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pdf_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    __table_args__ = (
        # Production date unique within tenant
        UniqueConstraint("tenant_id", "production_date", name="uq_production_summary_tenant_date"),
        Index("ix_production_summaries_tenant_date", "tenant_id", "production_date"),
    )


# =============================================================================
# PRODUCTION LOG (faktisk produksjon + svinn)
# =============================================================================

class ProductionLog(Base, TimestampMixin, TenantMixin):
    """
    Loggfor faktisk produksjon og svinn pr produkt pr dato.

    En rad pr (tenant_id, log_date, product_id). Bakeren registrerer:
    - actual_qty: hvor mye som faktisk ble produsert
    - waste_*: hvor mye som ble kassert (med arsak)

    planned_qty er en snapshot fra ordrene for sporbarhet selv om ordre endres senere.
    """
    __tablename__ = "production_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    log_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    planned_qty: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Planlagt produksjon (snapshot fra ordrene da loggen ble opprettet)"
    )
    actual_qty: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Faktisk produsert antall"
    )

    waste_returned: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Returnert fra kunde / ikke levert"
    )
    waste_burnt: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Brent / feilprodusert"
    )
    waste_quality: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Kassert pga kvalitet"
    )
    waste_other: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Annen kassasjon"
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Hvem registrerte
    logged_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    product: Mapped["Product"] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "log_date", "product_id",
                         name="uq_production_log_tenant_date_product"),
        Index("ix_production_logs_tenant_date", "tenant_id", "log_date"),
        CheckConstraint("actual_qty >= 0", name="check_prodlog_actual_nonneg"),
        CheckConstraint("waste_returned >= 0", name="check_prodlog_waste_returned_nonneg"),
        CheckConstraint("waste_burnt >= 0", name="check_prodlog_waste_burnt_nonneg"),
        CheckConstraint("waste_quality >= 0", name="check_prodlog_waste_quality_nonneg"),
        CheckConstraint("waste_other >= 0", name="check_prodlog_waste_other_nonneg"),
    )

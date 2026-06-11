"""
Pydantic schemas for API request/response validation.
"""
from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional, List
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator, computed_field
from pydantic.functional_validators import BeforeValidator
from typing_extensions import Annotated


# =============================================================================
# ENUMS (mirroring SQLAlchemy enums for API)
# =============================================================================

class SyncStatusEnum(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    CANCELLED = "cancelled"


class OrderStatusEnum(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    READY_FOR_DELIVERY = "ready_for_delivery"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class DayOfWeekEnum(int, Enum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


class DeliveryIssueTypeEnum(str, Enum):
    DAMAGED = "damaged"
    MISSING = "missing"
    WRONG_PRODUCT = "wrong_product"
    CUSTOMER_REFUSED = "customer_refused"
    ADDRESS_NOT_FOUND = "address_not_found"
    OTHER = "other"


class DeletionReasonEnum(str, Enum):
    DUPLICATE = "duplicate"
    MISTAKE = "mistake"
    CUSTOMER_REQUEST = "customer_request"
    BUSINESS_CLOSED = "business_closed"
    TEST_DATA = "test_data"
    OTHER = "other"


class VatClassEnum(str, Enum):
    """MVA-klasser iht. norsk regelverk."""
    FOOD_15 = "food_15"
    STANDARD_25 = "standard_25"
    REDUCED_12 = "reduced_12"
    ZERO = "zero"


class CustomerPriceTierEnum(str, Enum):
    PRICE_1 = "price_1"
    PRICE_2 = "price_2"
# =============================================================================
# BASE SCHEMAS
# =============================================================================

class TimestampSchema(BaseModel):
    created_at: datetime
    updated_at: datetime


# =============================================================================
# CUSTOMER SCHEMAS
# =============================================================================

class CustomerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    org_number: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    
    street_address: Optional[str] = Field(None, max_length=500)
    postal_code: Optional[str] = Field(None, max_length=20)
    city: Optional[str] = Field(None, max_length=100)
    country: str = Field(default="Norway", max_length=100)
    
    latitude: Optional[Decimal] = Field(None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(None, ge=-180, le=180)
    
    delivery_window_start: Optional[time] = None
    delivery_window_end: Optional[time] = None
    delivery_instructions: Optional[str] = None
    
    order_lead_days: int = Field(default=14, ge=7, le=84)
    susoft_price_tier: CustomerPriceTierEnum = Field(
        default=CustomerPriceTierEnum.PRICE_1,
        description="Hvilket SuSoft-prissett kunden bruker: price_1 eller price_2.",
    )
    delivers_on_holidays: bool = Field(
        default=False,
        description=(
            "Skal kunden få levering på helligdager? "
            "Sett True for hoteller, sykehus, sykehjem og lignende."
        ),
    )
    restrict_to_favorites: bool = Field(
        default=False,
        description=(
            "Hvis True kan kunden i portalen kun bestille produkter som finnes i favorittlisten."
        ),
    )
    is_active: bool = True
    parent_customer_id: Optional[int] = Field(
        default=None,
        description="Hvis satt: denne kunden er et utsalg under hovedkunden med denne IDen."
    )


class CustomerCreate(CustomerBase):
    susoft_customer_id: Optional[str] = Field(None, max_length=100)


class CustomerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    org_number: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    street_address: Optional[str] = Field(None, max_length=500)
    postal_code: Optional[str] = Field(None, max_length=20)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[Decimal] = Field(None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(None, ge=-180, le=180)
    delivery_window_start: Optional[time] = None
    delivery_window_end: Optional[time] = None
    delivery_instructions: Optional[str] = None
    order_lead_days: Optional[int] = Field(None, ge=7, le=84)
    susoft_price_tier: Optional[CustomerPriceTierEnum] = None
    delivers_on_holidays: Optional[bool] = None
    restrict_to_favorites: Optional[bool] = None
    is_active: Optional[bool] = None
    parent_customer_id: Optional[int] = None


class CustomerResponse(CustomerBase, TimestampSchema):
    id: int
    susoft_customer_id: Optional[str] = None
    susoft_last_synced_at: Optional[datetime] = None
    # Override: imported SuSoft data may contain malformed emails (e.g. ".@.").
    # Be lenient on output so listing customers never fails validation.
    email: Optional[str] = None

    # Indikator-flagg fylt ut av list-endepunktet for hurtig visning i UI.
    # Default False slik at enkelt-uthentinger fortsatt fungerer uten ekstra spørringer.
    has_active_template: bool = False
    has_portal_user: bool = False
    has_future_orders: bool = False

    model_config = ConfigDict(from_attributes=True)


class CustomerListResponse(BaseModel):
    items: List[CustomerResponse]
    total: int
    page: int
    page_size: int
    total_pages: int = 0


# =============================================================================
# PRODUCT SCHEMAS
# =============================================================================

class ProductBase(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    
    default_price: Decimal = Field(..., ge=0, decimal_places=2)
    alternative_price: Optional[Decimal] = Field(None, ge=0, decimal_places=2)
    unit: str = Field(default="stk", max_length=20)
    vat_rate: Decimal = Field(default=Decimal("15.00"), ge=0, le=100)
    alternative_vat_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    vat_class: VatClassEnum = Field(
        default=VatClassEnum.FOOD_15,
        description="MVA-klasse. FOOD_15 for bakerivarer, STANDARD_25 for andre varer.",
    )

    is_active: bool = True
    is_available_for_order: bool = True
    min_order_quantity: int = Field(default=1, ge=1)
    allergens: Optional[str] = Field(
        None, max_length=500,
        description="Komma-separert liste med allergener (f.eks. 'Hvete, Egg, Melk').",
    )

    # Produksjonsplanlegging
    batch_size: int = Field(
        default=1, ge=1,
        description="Standard batch-størrelse for baking. Antall pr. ovnsbrett/deig.",
    )
    production_step: Optional[str] = Field(
        default=None, max_length=100,
        description="Produksjons-stasjon, f.eks. 'Ovn 1', 'Bakebenk', 'Stekeovn'.",
    )
    production_lead_minutes: int = Field(
        default=0, ge=0,
        description="Estimert tid pr. batch i minutter (heving + steking).",
    )
    production_days: int = Field(
        default=0, ge=0, le=14,
        description="Antall produksjonsdager varen krever. Bestemmer tidligst mulig leveringsdato i portalen.",
    )


class ProductCreate(ProductBase):
    susoft_product_id: Optional[str] = Field(None, max_length=100)


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    default_price: Optional[Decimal] = Field(None, ge=0)
    unit: Optional[str] = Field(None, max_length=20)
    vat_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    vat_class: Optional[VatClassEnum] = None
    is_active: Optional[bool] = None
    is_available_for_order: Optional[bool] = None
    min_order_quantity: Optional[int] = Field(None, ge=1)
    allergens: Optional[str] = Field(None, max_length=500)
    batch_size: Optional[int] = Field(None, ge=1)
    production_step: Optional[str] = Field(None, max_length=100)
    production_lead_minutes: Optional[int] = Field(None, ge=0)
    production_days: Optional[int] = Field(None, ge=0, le=14)


class ProductResponse(ProductBase, TimestampSchema):
    id: int
    susoft_product_id: Optional[str] = None
    susoft_last_synced_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# CUSTOMER PRODUCT PRICE SCHEMAS
# =============================================================================

class CustomerProductPriceBase(BaseModel):
    customer_id: int
    product_id: int
    price: Decimal = Field(..., ge=0, decimal_places=2)
    effective_from_date: date


class CustomerProductPriceCreate(CustomerProductPriceBase):
    pass


class CustomerProductPriceUpdate(BaseModel):
    price: Optional[Decimal] = Field(None, ge=0)
    effective_from_date: Optional[date] = None


class CustomerProductPriceResponse(CustomerProductPriceBase, TimestampSchema):
    id: int
    effective_to_date: Optional[date] = None
    orders_updated: bool = False
    susoft_sync_triggered: bool = False
    
    model_config = ConfigDict(from_attributes=True)


class PriceLookupRequest(BaseModel):
    """Request to get effective price for a customer/product on a date."""
    customer_id: int
    product_id: int
    target_date: date


class PriceLookupResponse(BaseModel):
    """Response with the effective price."""
    customer_id: int
    product_id: int
    target_date: date
    effective_price: Decimal
    is_customer_specific: bool  # True if from CustomerProductPrice, False if default
    price_entry_id: Optional[int] = None  # ID of CustomerProductPrice if applicable


# =============================================================================
# MASTER TEMPLATE SCHEMAS
# =============================================================================

class MasterTemplateItemBase(BaseModel):
    product_id: int
    day_of_week: int = Field(..., ge=1, le=7)
    quantity: int = Field(..., ge=0)
    notes: Optional[str] = Field(None, max_length=500)


class MasterTemplateItemCreate(MasterTemplateItemBase):
    pass


class MasterTemplateItemUpdate(BaseModel):
    quantity: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=500)


class MasterTemplateItemResponse(MasterTemplateItemBase, TimestampSchema):
    id: int
    template_id: int
    
    model_config = ConfigDict(from_attributes=True)


class MasterTemplateBase(BaseModel):
    customer_id: int
    name: str = Field(default="Standard Ukentlig Ordre", max_length=255)
    description: Optional[str] = None
    default_reference: Optional[str] = Field(None, max_length=255)
    is_active: bool = True


class MasterTemplateCreate(MasterTemplateBase):
    items: Optional[List[MasterTemplateItemCreate]] = []


class MasterTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    default_reference: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


class MasterTemplateResponse(MasterTemplateBase, TimestampSchema):
    id: int
    last_generated_for_date: Optional[date] = None
    items: List[MasterTemplateItemResponse] = []
    
    model_config = ConfigDict(from_attributes=True)


class TemplateMatrixView(BaseModel):
    """
    Matrix view of a template: products as rows, days as columns.
    Useful for the "Order Matrix" UI.
    """
    template_id: int
    customer_id: int
    customer_name: str
    matrix: dict[int, dict[int, int]]  # {product_id: {day_of_week: quantity}}
    products: List[ProductResponse]


# =============================================================================
# ORDER SCHEMAS
# =============================================================================

class OrderLineBase(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)
    notes: Optional[str] = Field(None, max_length=500)


class OrderLineCreate(OrderLineBase):
    pass


class OrderLineUpdate(BaseModel):
    quantity: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = Field(None, max_length=500)


class OrderLineResponse(OrderLineBase, TimestampSchema):
    id: int
    order_id: int
    unit_price: Decimal
    vat_rate: Decimal
    line_amount_excl_vat: Decimal
    line_vat: Decimal
    line_amount_incl_vat: Decimal
    is_adhoc_quantity: bool = False
    original_template_quantity: Optional[int] = None
    delivered_quantity: Optional[int] = None
    waste_quantity: int = 0
    return_quantity: int = 0
    
    model_config = ConfigDict(from_attributes=True)


class OrderBase(BaseModel):
    customer_id: int
    delivery_date: date
    reference: Optional[str] = Field(None, max_length=255)
    internal_notes: Optional[str] = None
    customer_notes: Optional[str] = None


class OrderCreate(OrderBase):
    lines: List[OrderLineCreate] = []


class OrderUpdate(BaseModel):
    status: Optional[OrderStatusEnum] = None
    delivery_date: Optional[date] = None
    reference: Optional[str] = Field(None, max_length=255)
    internal_notes: Optional[str] = None
    customer_notes: Optional[str] = None


class OrderResponse(OrderBase, TimestampSchema):
    id: int
    order_uuid: UUID
    order_no_seq: Optional[int] = None
    order_no_display: Optional[str] = None
    status: OrderStatusEnum
    susoft_order_id: Optional[str] = None
    susoft_uuid: Optional[str] = None
    susoft_order_no: Optional[str] = None
    sync_status: SyncStatusEnum
    sync_error_message: Optional[str] = None
    last_sync_attempt: Optional[datetime] = None

    susoft_invoice_no: Optional[str] = None
    invoiced_at: Optional[datetime] = None
    source: Optional[str] = None
    
    generated_from_template_id: Optional[int] = None
    is_adhoc_modified: bool = False
    
    total_amount_excl_vat: Decimal
    total_vat: Decimal
    total_amount_incl_vat: Decimal
    
    is_locked: bool = False
    locked_at: Optional[datetime] = None
    is_hidden: bool = Field(False, validation_alias="is_deleted")
    needs_review: bool = False
    reviewed_at: Optional[datetime] = None

    route_position: Optional[int] = None
    estimated_delivery_time: Optional[datetime] = None
    actual_delivery_time: Optional[datetime] = None
    delivered_by_user_id: Optional[int] = None
    delivery_notes: Optional[str] = None
    delivery_photo_url: Optional[str] = None
    
    customer_name: Optional[str] = None  # Populated from customer relationship
    
    lines: List[OrderLineResponse] = []
    
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderListResponse(BaseModel):
    items: List[OrderResponse]
    total: int
    page: int
    page_size: int
    total_pages: int = 0


class OrderWithCustomer(OrderResponse):
    """Order response with nested customer details for driver view."""
    customer: CustomerResponse


# =============================================================================
# ORDER AMENDMENTS (endringslogg / avvik)
# =============================================================================

class OrderAmendmentCreate(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)
    reference: Optional[str] = Field(None, max_length=255)
    changes_summary: Optional[str] = Field(None, max_length=4000)


class OrderAmendmentResponse(BaseModel):
    id: int
    order_id: int
    amended_at: datetime
    amended_by_user_id: Optional[int] = None
    amended_by_name: Optional[str] = None
    reason: str
    reference: Optional[str] = None
    changes_summary: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# AD-HOC OVERRIDE SCHEMAS
# =============================================================================

class OrderDateOverrideBase(BaseModel):
    customer_id: int
    product_id: int
    override_date: date
    quantity: int = Field(..., ge=0)
    reason: Optional[str] = Field(None, max_length=500)


class OrderDateOverrideCreate(OrderDateOverrideBase):
    pass


class OrderDateOverrideResponse(OrderDateOverrideBase, TimestampSchema):
    id: int
    applied_to_order_id: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# HOLIDAY & BLOCKED DATE SCHEMAS
# =============================================================================

class HolidayBase(BaseModel):
    holiday_date: date
    name: str = Field(..., max_length=255)
    is_full_day: bool = True
    year: Optional[int] = None


class HolidayCreate(HolidayBase):
    pass


class HolidayResponse(HolidayBase, TimestampSchema):
    id: int
    
    model_config = ConfigDict(from_attributes=True)


class CustomerBlockedDateBase(BaseModel):
    customer_id: int
    start_date: date
    end_date: date
    reason: Optional[str] = Field(None, max_length=500)
    
    @field_validator('end_date')
    @classmethod
    def end_date_after_start(cls, v: date, info) -> date:
        if 'start_date' in info.data and v < info.data['start_date']:
            raise ValueError('end_date must be >= start_date')
        return v


class CustomerBlockedDateCreate(CustomerBlockedDateBase):
    pass


class CustomerBlockedDateResponse(CustomerBlockedDateBase, TimestampSchema):
    id: int
    
    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# DELIVERY & DRIVER SCHEMAS
# =============================================================================

class RouteBase(BaseModel):
    """Base schema for delivery routes."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    delivery_days: List[int] = Field(default=[1, 2, 3, 4, 5], description="Days of week (1=Mon, 7=Sun)")
    default_start_time: Optional[time] = None
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0)
    
    @field_validator('delivery_days')
    @classmethod
    def validate_delivery_days(cls, v: List[int]) -> List[int]:
        for day in v:
            if not 1 <= day <= 7:
                raise ValueError('Days must be between 1 (Monday) and 7 (Sunday)')
        return sorted(set(v))


class RouteCreate(RouteBase):
    pass


class RouteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    delivery_days: Optional[List[int]] = None
    default_start_time: Optional[time] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = Field(None, ge=0)


class RouteResponse(RouteBase, TimestampSchema):
    id: int
    
    model_config = ConfigDict(from_attributes=True)


class RouteWithCustomers(RouteResponse):
    """Route with nested customer list."""
    customers: List[CustomerResponse] = []
    customer_count: int = 0


class RouteListResponse(BaseModel):
    items: List[RouteResponse]
    total: int


class RouteCustomerAssignment(BaseModel):
    """Request to assign customers to a route."""
    customer_ids: List[int]


class RouteCustomerReorder(BaseModel):
    """Request to reorder customers within a route."""
    customer_order: List[int]  # List of customer IDs in desired order


class RoutePostalRuleBase(BaseModel):
    from_code: str = Field(..., min_length=1, max_length=10)
    to_code: str = Field(..., min_length=1, max_length=10)
    label: Optional[str] = Field(None, max_length=100)

    @field_validator('from_code', 'to_code')
    @classmethod
    def strip_code(cls, v: str) -> str:
        return v.strip()


class RoutePostalRuleCreate(RoutePostalRuleBase):
    pass


class RoutePostalRuleResponse(RoutePostalRuleBase):
    id: int
    route_id: int
    model_config = ConfigDict(from_attributes=True)


class RoutePostalAutoAssignPreview(BaseModel):
    matched_customers: int
    new_assignments: int
    already_on_route: int
    conflicts: int  # kunder som allerede er paa en annen rute
    customer_ids_to_assign: List[int]
    conflict_examples: List[dict] = []


class DeliveryRouteResponse(BaseModel):
    id: int
    route_date: date
    total_distance_km: Optional[Decimal] = None
    total_duration_minutes: Optional[int] = None
    optimization_timestamp: Optional[datetime] = None
    route_data: Optional[dict] = None
    assigned_driver_id: Optional[int] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class DeliveryStop(BaseModel):
    """Single stop in a delivery route."""
    order_id: int
    customer_id: int
    customer_name: str
    address: str
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    delivery_window_start: Optional[time] = None
    delivery_window_end: Optional[time] = None
    estimated_arrival: Optional[datetime] = None
    route_position: int


class DriverDeliveryView(BaseModel):
    """Mobile-friendly view for drivers."""
    route_date: date
    driver_name: str
    total_stops: int
    completed_stops: int
    stops: List[DeliveryStop]


class DeliveryConfirmation(BaseModel):
    """Driver confirms a delivery."""
    order_id: int
    delivery_notes: Optional[str] = None
    signature: Optional[str] = None  # Base64 encoded signature image


class DeliveryIssueCreate(BaseModel):
    order_id: int
    product_id: Optional[int] = None
    issue_type: DeliveryIssueTypeEnum
    quantity_affected: Optional[int] = Field(None, ge=0)
    description: str = Field(..., min_length=1)


class DeliveryIssueResponse(DeliveryIssueCreate, TimestampSchema):
    id: int
    reported_by_user_id: int
    reported_at: datetime
    is_resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# PANIC BUTTON / BATCH OPERATIONS
# =============================================================================

class PanicCancelRequest(BaseModel):
    """Batch cancel all orders for a specific date."""
    target_date: date
    reason: str = Field(..., min_length=10, max_length=500)
    
    # Optional: only cancel specific customers
    customer_ids: Optional[List[int]] = None


class PanicCancelResponse(BaseModel):
    target_date: date
    orders_cancelled: int
    orders_failed: int
    susoft_updates_triggered: int
    audit_log_id: int


class BatchPriceUpdateRequest(BaseModel):
    """Batch update prices - triggers order updates and SuSoft sync."""
    price_entry_id: int
    update_existing_orders: bool = True
    sync_to_susoft: bool = True


class BatchPriceUpdateResponse(BaseModel):
    price_entry_id: int
    orders_updated: int
    susoft_sync_scheduled: bool


# =============================================================================
# SYNC & ALERTS SCHEMAS
# =============================================================================

class SyncLogResponse(BaseModel):
    id: int
    sync_type: str
    entity_type: str
    entity_id: int
    http_method: str
    endpoint: str
    response_status_code: Optional[int] = None
    was_successful: bool
    error_message: Optional[str] = None
    attempt_number: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AdminAlertResponse(BaseModel):
    id: int
    alert_type: str
    severity: str
    title: str
    message: str
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None
    is_read: bool
    is_resolved: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AdminAlertAcknowledge(BaseModel):
    resolved: bool = False
    resolution_notes: Optional[str] = None


# =============================================================================
# AUDIT SCHEMAS
# =============================================================================

class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    entity_type: str
    entity_id: int
    action: str
    deletion_reason_category: Optional[str] = None
    deletion_reason_text: Optional[str] = None
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    
    model_config = ConfigDict(from_attributes=True)


class DeleteRequest(BaseModel):
    """Required fields for any delete operation (soft delete)."""
    reason_category: DeletionReasonEnum
    reason_text: str = Field(..., min_length=5, max_length=500)


# =============================================================================
# SUSOFT SYNC SCHEMAS
# =============================================================================

class SuSoftCustomerSync(BaseModel):
    """Data received from SuSoft customer sync."""
    susoft_customer_id: str
    name: str
    company_name: Optional[str] = None
    org_number: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None


class SuSoftProductSync(BaseModel):
    """Data received from SuSoft product sync."""
    susoft_product_id: str
    sku: str
    name: str
    description: Optional[str] = None
    price: Decimal
    vat_rate: Optional[Decimal] = None


class SuSoftOrderRequest(BaseModel):
    """Order data to send to SuSoft."""
    customer_id: str  # susoft_customer_id
    delivery_date: date
    lines: List[dict]
    notes: Optional[str] = None


class SuSoftOrderResponse(BaseModel):
    """Response from SuSoft after order creation."""
    susoft_order_id: str
    status: str
    created_at: datetime

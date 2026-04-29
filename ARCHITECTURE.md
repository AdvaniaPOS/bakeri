# Lampeland Bakeri - Ordresystem
## Komplett Systemarkitektur og Spesifikasjon

> **For GitHub Copilot**: Dette dokumentet beskriver alle komponenter, datamodeller, API-endepunkter og forretningsregler for systemet. Bruk dette som referanse når du genererer kode.

---

## 1. SYSTEMOVERSIKT

### 1.1 Formål
Et B2B ordresystem for Lampeland Bakeri som håndterer:
- **Abonnementsordrer**: Kunder bestiller faste leveringer på spesifikke ukedager
- **Rullerende ordregenerering**: Ordrer genereres automatisk 14-60 dager frem i tid
- **Susoft-integrasjon**: Alle ordrer synkroniseres til Susoft POS for fakturering
- **Ruteplanlegging**: Google Maps-basert ruteoptimalisering for sjåfører
- **Produksjonsrapporter**: Aggregerte bake-lister for produksjon

### 1.2 Teknisk Stack
```
Backend:  Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Celery
Frontend: React 18 / Vite / TailwindCSS
Database: PostgreSQL (prod) / SQLite (dev)
Cache:    Redis (for Celery)
API:      Susoft REST API v3.1 (https://api.susoft.com:4443)
```

---

## 2. DATAMODELLER

### 2.1 Route (MANGLER - MÅ IMPLEMENTERES)
```python
# Legg til i app/models.py

class Route(Base, TimestampMixin):
    """
    Leveringsrute for gruppering av kunder.
    
    Eksempel: "Rute 1 - Kongsberg" inneholder alle kunder i Kongsberg-området.
    Kunder tildeles en rute manuelt av admin.
    """
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        comment="Rutenavn, f.eks. 'Rute 1 - Kongsberg'"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Leveringsdager for denne ruten
    delivery_days: Mapped[List[int]] = mapped_column(
        JSON, nullable=False, default=list,
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
    
    __table_args__ = (
        Index("ix_routes_active", "is_active", "sort_order"),
    )
```

### 2.2 Oppdater Customer-modellen
```python
# Legg til i Customer-klassen i app/models.py

    # Route relationship (erstatt dette feltet)
    route_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("routes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    route: Mapped[Optional["Route"]] = relationship(back_populates="customers")
```

### 2.3 DailyProductionSummary (NY - For produksjonsrapporter)
```python
class DailyProductionSummary(Base, TimestampMixin):
    """
    Aggregert produksjonsrapport per dag.
    Genereres automatisk når ordrer låses (kl 15:00 dagen før).
    """
    __tablename__ = "daily_production_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    production_date: Mapped[date] = mapped_column(
        Date, unique=True, nullable=False, index=True,
        comment="Leveringsdato for denne produksjonen"
    )
    
    # Aggregerte produkttall som JSON
    # Format: [{"product_id": 1, "product_name": "Kneipp", "total_quantity": 450, "unit": "stk"}]
    product_totals: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment="Aggregerte produktmengedr"
    )
    
    # Metadata
    total_orders: Mapped[int] = mapped_column(Integer, nullable=False)
    total_customers: Mapped[int] = mapped_column(Integer, nullable=False)
    total_order_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Status
    is_finalized: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Låst etter produksjon er startet"
    )
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # PDF generering
    pdf_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pdf_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

---

## 3. API ENDEPUNKTER

### 3.1 Routes API (NY FIL: app/api/routes.py)
```python
"""
Route management API endpoints.

Handles:
- CRUD for delivery routes
- Customer assignment to routes
- Route-based order filtering
"""
from datetime import date, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Route, Customer, Order
from ..schemas import (
    RouteCreate, RouteUpdate, RouteResponse, RouteWithCustomers,
    RouteListResponse
)

router = APIRouter(prefix="/routes", tags=["Routes"])


@router.get("", response_model=RouteListResponse)
async def list_routes(
    include_inactive: bool = False,
    db: Session = Depends(get_db)
):
    """List all delivery routes."""
    query = select(Route).order_by(Route.sort_order, Route.name)
    if not include_inactive:
        query = query.where(Route.is_active == True)
    
    routes = db.execute(query).scalars().all()
    return {"routes": routes, "total": len(routes)}


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_route(
    route_data: RouteCreate,
    db: Session = Depends(get_db)
):
    """Create a new delivery route."""
    route = Route(**route_data.model_dump())
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


@router.get("/{route_id}", response_model=RouteWithCustomers)
async def get_route(
    route_id: int,
    db: Session = Depends(get_db)
):
    """Get route with assigned customers."""
    route = db.execute(
        select(Route)
        .where(Route.id == route_id)
        .options(selectinload(Route.customers))
    ).scalar_one_or_none()
    
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


@router.put("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: int,
    route_data: RouteUpdate,
    db: Session = Depends(get_db)
):
    """Update a delivery route."""
    route = db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    
    for key, value in route_data.model_dump(exclude_unset=True).items():
        setattr(route, key, value)
    
    db.commit()
    db.refresh(route)
    return route


@router.post("/{route_id}/assign-customers")
async def assign_customers_to_route(
    route_id: int,
    customer_ids: List[int],
    db: Session = Depends(get_db)
):
    """Assign multiple customers to a route."""
    route = db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    
    customers = db.execute(
        select(Customer).where(Customer.id.in_(customer_ids))
    ).scalars().all()
    
    for customer in customers:
        customer.route_id = route_id
    
    db.commit()
    return {"assigned": len(customers)}


@router.get("/{route_id}/orders/{delivery_date}", response_model=List[dict])
async def get_route_orders(
    route_id: int,
    delivery_date: date,
    db: Session = Depends(get_db)
):
    """
    Get all orders for a route on a specific date.
    Returns orders sorted by route_position for optimal delivery order.
    """
    orders = db.execute(
        select(Order)
        .join(Customer)
        .where(
            Customer.route_id == route_id,
            Order.delivery_date == delivery_date,
            Order.is_deleted == False
        )
        .options(selectinload(Order.customer), selectinload(Order.lines))
        .order_by(Order.route_position)
    ).scalars().all()
    
    return orders
```

### 3.2 Production Reports API (NY FIL: app/api/reports.py)
```python
"""
Production and delivery reports API.

Provides:
- Daily production summaries (aggregated product quantities)
- Route delivery lists
- Customer order history
- Packing lists (pakksedler)
"""
from datetime import date, datetime, timedelta
from typing import List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import (
    Order, OrderLine, Customer, Product, Route, 
    DailyProductionSummary, OrderStatus
)
from ..schemas import (
    ProductionReportResponse, RouteDeliveryList,
    PackingSlipResponse, CustomerOrderHistory
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/production/{target_date}", response_model=ProductionReportResponse)
async def get_production_report(
    target_date: date,
    db: Session = Depends(get_db)
):
    """
    Aggregert produksjonsrapport for en gitt dato.
    
    Viser totalt antall av hvert produkt som må produseres for alle ordrer.
    Brukes av bakerne for å vite hvor mye deig som skal settes.
    """
    # Aggreger alle ordrelinjer for denne datoen
    results = db.execute(
        select(
            Product.id,
            Product.name,
            Product.category,
            Product.unit,
            func.sum(OrderLine.quantity).label("total_quantity")
        )
        .join(OrderLine)
        .join(Order)
        .where(
            Order.delivery_date == target_date,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED
        )
        .group_by(Product.id, Product.name, Product.category, Product.unit)
        .order_by(Product.category, Product.name)
    ).all()
    
    # Tell totaler
    order_count = db.execute(
        select(func.count(Order.id))
        .where(
            Order.delivery_date == target_date,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED
        )
    ).scalar()
    
    customer_count = db.execute(
        select(func.count(func.distinct(Order.customer_id)))
        .where(
            Order.delivery_date == target_date,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED
        )
    ).scalar()
    
    products = [
        {
            "product_id": r.id,
            "product_name": r.name,
            "category": r.category,
            "unit": r.unit,
            "total_quantity": r.total_quantity
        }
        for r in results
    ]
    
    return {
        "production_date": target_date,
        "products": products,
        "total_orders": order_count,
        "total_customers": customer_count,
        "generated_at": datetime.utcnow()
    }


@router.get("/delivery-list/{route_id}/{target_date}", response_model=RouteDeliveryList)
async def get_route_delivery_list(
    route_id: int,
    target_date: date,
    db: Session = Depends(get_db)
):
    """
    Kjøreliste for en rute på en gitt dato.
    
    Returnerer alle kunder og deres ordrer, sortert etter ruteposisjon.
    Inkluderer adresser for Google Maps-navigasjon.
    """
    route = db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    
    orders = db.execute(
        select(Order)
        .join(Customer)
        .where(
            Customer.route_id == route_id,
            Order.delivery_date == target_date,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED
        )
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product)
        )
        .order_by(Order.route_position)
    ).scalars().all()
    
    # Bygg kjøreliste med adresser
    stops = []
    for order in orders:
        customer = order.customer
        stops.append({
            "order_id": order.id,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "company_name": customer.company_name,
            "address": f"{customer.street_address}, {customer.postal_code} {customer.city}",
            "latitude": float(customer.latitude) if customer.latitude else None,
            "longitude": float(customer.longitude) if customer.longitude else None,
            "delivery_window": {
                "start": str(customer.delivery_window_start) if customer.delivery_window_start else None,
                "end": str(customer.delivery_window_end) if customer.delivery_window_end else None
            },
            "delivery_instructions": customer.delivery_instructions,
            "phone": customer.phone,
            "lines": [
                {
                    "product_name": line.product.name,
                    "quantity": line.quantity,
                    "unit": line.product.unit
                }
                for line in order.lines
            ],
            "route_position": order.route_position
        })
    
    return {
        "route_id": route_id,
        "route_name": route.name,
        "delivery_date": target_date,
        "stops": stops,
        "total_stops": len(stops)
    }


@router.get("/delivery-list/{route_id}/{target_date}/google-maps-url")
async def get_google_maps_route_url(
    route_id: int,
    target_date: date,
    db: Session = Depends(get_db)
):
    """
    Genererer en Google Maps URL for optimal kjørerute.
    
    Bruker alle kundeadresser på ruten og returnerer en URL
    som kan åpnes direkte i Google Maps for navigasjon.
    """
    orders = db.execute(
        select(Order)
        .join(Customer)
        .where(
            Customer.route_id == route_id,
            Order.delivery_date == target_date,
            Order.is_deleted == False,
            Order.status != OrderStatus.CANCELLED
        )
        .options(selectinload(Order.customer))
        .order_by(Order.route_position)
    ).scalars().all()
    
    if not orders:
        raise HTTPException(status_code=404, detail="No orders found for this route and date")
    
    # Bygg Google Maps URL
    # Format: https://www.google.com/maps/dir/origin/waypoint1/waypoint2/.../destination
    
    addresses = []
    for order in orders:
        customer = order.customer
        if customer.latitude and customer.longitude:
            # Bruk koordinater hvis tilgjengelig (mer presist)
            addresses.append(f"{customer.latitude},{customer.longitude}")
        elif customer.street_address:
            # Fallback til adresse
            addr = f"{customer.street_address}, {customer.postal_code} {customer.city}, Norway"
            addresses.append(addr.replace(" ", "+"))
    
    if len(addresses) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 addresses for route")
    
    # Første adresse er start, siste er slutt, resten er waypoints
    base_url = "https://www.google.com/maps/dir"
    route_url = base_url + "/" + "/".join(addresses)
    
    return {
        "url": route_url,
        "stops_count": len(addresses),
        "note": "URL åpner Google Maps med alle stopp i rekkefølge"
    }


@router.get("/packing-slip/{order_id}")
async def get_packing_slip(
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    Genererer pakkseddel for en ordre.
    
    Returnerer data for å printe pakkseddel som legges med leveransen.
    """
    order = db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product)
        )
    ).scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    customer = order.customer
    
    return {
        "order_id": order.id,
        "order_uuid": str(order.order_uuid),
        "delivery_date": order.delivery_date,
        "customer": {
            "name": customer.name,
            "company_name": customer.company_name,
            "address": f"{customer.street_address}",
            "postal_code": customer.postal_code,
            "city": customer.city,
            "contact_person": customer.contact_person,
            "phone": customer.phone
        },
        "lines": [
            {
                "product_name": line.product.name,
                "product_sku": line.product.sku,
                "quantity": line.quantity,
                "unit": line.product.unit
            }
            for line in order.lines
        ],
        "total_lines": len(order.lines),
        "total_items": sum(line.quantity for line in order.lines),
        "internal_notes": order.internal_notes,
        "customer_notes": order.customer_notes,
        "generated_at": datetime.utcnow()
    }


@router.get("/customer-history/{customer_id}")
async def get_customer_order_history(
    customer_id: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Kundehistorikk - alle ordrer for en kunde.
    """
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    query = (
        select(Order)
        .where(
            Order.customer_id == customer_id,
            Order.is_deleted == False
        )
        .order_by(Order.delivery_date.desc())
    )
    
    if from_date:
        query = query.where(Order.delivery_date >= from_date)
    if to_date:
        query = query.where(Order.delivery_date <= to_date)
    
    # Pagination
    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar()
    
    orders = db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
        .options(selectinload(Order.lines))
    ).scalars().all()
    
    return {
        "customer_id": customer_id,
        "customer_name": customer.name,
        "orders": orders,
        "total": total,
        "page": page,
        "page_size": page_size
    }
```

### 3.3 Susoft Sync API (OPPDATER: app/api/susoft_sync.py)
```python
"""
SuSoft synchronization API endpoints.

Manual triggers for:
- Customer sync from SuSoft
- Product sync from SuSoft
- Order push to SuSoft
- Order update (PUT) to SuSoft
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, Product, Order, SyncStatus, SyncLog
from ..services.susoft import SuSoftService, SuSoftAPIError

router = APIRouter(prefix="/susoft", tags=["SuSoft Integration"])


@router.post("/sync/customers")
async def sync_customers_from_susoft(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Sync all customers from SuSoft to local database.
    
    - Henter alle kunder fra Susoft GET /customer/list
    - Oppdaterer eksisterende kunder basert på susoft_customer_id
    - Oppretter nye kunder hvis de ikke finnes
    """
    service = SuSoftService(db)
    
    try:
        customers = service.get_all_customers()
        
        created = 0
        updated = 0
        
        for susoft_customer in customers:
            # Sjekk om kunden finnes
            existing = db.execute(
                select(Customer).where(
                    Customer.susoft_customer_id == str(susoft_customer.get("id"))
                )
            ).scalar_one_or_none()
            
            if existing:
                # Oppdater eksisterende
                existing.name = susoft_customer.get("firstname", "") + " " + susoft_customer.get("lastname", "")
                existing.name = existing.name.strip() or susoft_customer.get("companyName", "Ukjent")
                existing.company_name = susoft_customer.get("companyName")
                existing.email = susoft_customer.get("email")
                existing.phone = susoft_customer.get("mobile") or susoft_customer.get("phone")
                existing.street_address = susoft_customer.get("address")
                existing.postal_code = susoft_customer.get("postalCode")
                existing.city = susoft_customer.get("city")
                existing.susoft_last_synced_at = datetime.utcnow()
                updated += 1
            else:
                # Opprett ny kunde
                name = susoft_customer.get("firstname", "") + " " + susoft_customer.get("lastname", "")
                name = name.strip() or susoft_customer.get("companyName", "Ukjent")
                
                new_customer = Customer(
                    susoft_customer_id=str(susoft_customer.get("id")),
                    name=name,
                    company_name=susoft_customer.get("companyName"),
                    email=susoft_customer.get("email"),
                    phone=susoft_customer.get("mobile") or susoft_customer.get("phone"),
                    street_address=susoft_customer.get("address"),
                    postal_code=susoft_customer.get("postalCode"),
                    city=susoft_customer.get("city"),
                    susoft_last_synced_at=datetime.utcnow()
                )
                db.add(new_customer)
                created += 1
        
        db.commit()
        
        return {
            "success": True,
            "customers_created": created,
            "customers_updated": updated,
            "total_from_susoft": len(customers)
        }
        
    except SuSoftAPIError as e:
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")


@router.post("/sync/products")
async def sync_products_from_susoft(
    db: Session = Depends(get_db)
):
    """
    Sync all products from SuSoft to local database.
    
    - Henter produkter fra Susoft GET /product/list
    - Oppdaterer priser (default_price) fra Susoft
    - Oppretter nye produkter hvis de ikke finnes
    - Overskriver IKKE kundepriser (CustomPrice)
    """
    service = SuSoftService(db)
    
    try:
        products = service.get_all_products()
        
        created = 0
        updated = 0
        
        for susoft_product in products:
            existing = db.execute(
                select(Product).where(
                    Product.susoft_product_id == str(susoft_product.get("id"))
                )
            ).scalar_one_or_none()
            
            if existing:
                existing.name = susoft_product.get("name", existing.name)
                existing.default_price = susoft_product.get("price", existing.default_price)
                existing.category = susoft_product.get("category", {}).get("name")
                existing.vat_rate = susoft_product.get("vatRate", existing.vat_rate)
                existing.susoft_last_synced_at = datetime.utcnow()
                updated += 1
            else:
                new_product = Product(
                    susoft_product_id=str(susoft_product.get("id")),
                    sku=susoft_product.get("barcode") or f"SKU-{susoft_product.get('id')}",
                    name=susoft_product.get("name", "Ukjent produkt"),
                    default_price=susoft_product.get("price", 0),
                    category=susoft_product.get("category", {}).get("name"),
                    vat_rate=susoft_product.get("vatRate", 15.0),
                    susoft_last_synced_at=datetime.utcnow()
                )
                db.add(new_product)
                created += 1
        
        db.commit()
        
        return {
            "success": True,
            "products_created": created,
            "products_updated": updated,
            "total_from_susoft": len(products)
        }
        
    except SuSoftAPIError as e:
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")


@router.post("/push/order/{order_id}")
async def push_order_to_susoft(
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    Send en ordre til Susoft via POST /order.
    
    Bruker:
    - isForInvoicing: true (faktura-ordre)
    - alternativeId: vår ordresystem-ID for kobling
    
    Lagrer susoft_order_id tilbake i vår database.
    """
    from ..schemas import OrderResponse
    
    order = db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product)
        )
    ).scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.susoft_order_id:
        raise HTTPException(
            status_code=400, 
            detail=f"Order already synced to SuSoft with ID: {order.susoft_order_id}"
        )
    
    service = SuSoftService(db)
    
    try:
        susoft_order_id = service.create_order(order)
        
        order.susoft_order_id = susoft_order_id
        order.sync_status = SyncStatus.SYNCED
        order.last_sync_attempt = datetime.utcnow()
        order.sync_error_message = None
        
        db.commit()
        
        return {
            "success": True,
            "order_id": order.id,
            "susoft_order_id": susoft_order_id
        }
        
    except SuSoftAPIError as e:
        order.sync_status = SyncStatus.FAILED
        order.last_sync_attempt = datetime.utcnow()
        order.sync_error_message = e.message
        order.sync_retry_count += 1
        db.commit()
        
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")


@router.put("/update/order/{order_id}")
async def update_order_in_susoft(
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    Oppdater en eksisterende ordre i Susoft via PUT /order/{id}.
    
    Brukes når:
    - Admin endrer antall på en ordre som allerede er sendt til Susoft
    - Priser endres på fremtidige ordrer
    
    VIKTIG: Krever at order.susoft_order_id er satt (ordre må være synket først)
    """
    order = db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.customer),
            selectinload(Order.lines).selectinload(OrderLine.product)
        )
    ).scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if not order.susoft_order_id:
        raise HTTPException(
            status_code=400, 
            detail="Order has not been synced to SuSoft yet. Use POST to create first."
        )
    
    service = SuSoftService(db)
    
    try:
        success = service.update_order(order)
        
        if success:
            order.last_sync_attempt = datetime.utcnow()
            order.sync_error_message = None
            
            # Logg oppdateringen
            from ..models import AuditLog, AuditAction
            audit = AuditLog(
                entity_type="order",
                entity_id=order.id,
                action=AuditAction.SYNC,
                new_values={
                    "action": "PUT",
                    "susoft_order_id": order.susoft_order_id
                }
            )
            db.add(audit)
            db.commit()
            
            return {
                "success": True,
                "order_id": order.id,
                "susoft_order_id": order.susoft_order_id,
                "message": "Order updated in SuSoft"
            }
        else:
            raise HTTPException(status_code=502, detail="SuSoft update failed")
        
    except SuSoftAPIError as e:
        order.sync_status = SyncStatus.FAILED
        order.last_sync_attempt = datetime.utcnow()
        order.sync_error_message = e.message
        db.commit()
        
        raise HTTPException(status_code=502, detail=f"SuSoft API error: {e.message}")


@router.get("/status")
async def get_sync_status(
    db: Session = Depends(get_db)
):
    """
    Hent status for synkronisering.
    
    Viser:
    - Antall ordrer som venter på sync
    - Antall feilet sync
    - Siste vellykkede sync
    """
    from sqlalchemy import func
    
    pending = db.execute(
        select(func.count(Order.id))
        .where(Order.sync_status == SyncStatus.PENDING)
    ).scalar()
    
    failed = db.execute(
        select(func.count(Order.id))
        .where(Order.sync_status == SyncStatus.FAILED)
    ).scalar()
    
    last_success = db.execute(
        select(SyncLog)
        .where(SyncLog.was_successful == True)
        .order_by(SyncLog.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    
    return {
        "pending_orders": pending,
        "failed_orders": failed,
        "last_successful_sync": last_success.created_at if last_success else None
    }
```

---

## 4. PYDANTIC SCHEMAS (Oppdater app/schemas.py)

```python
# Legg til disse i app/schemas.py

# =============================================================================
# ROUTE SCHEMAS
# =============================================================================

class RouteBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    delivery_days: List[int] = Field(default=[1, 2, 3, 4, 5])  # Man-Fre
    default_start_time: Optional[time] = Field(default=time(7, 0))
    is_active: bool = True
    sort_order: int = 0


class RouteCreate(RouteBase):
    pass


class RouteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    delivery_days: Optional[List[int]] = None
    default_start_time: Optional[time] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class RouteResponse(RouteBase, TimestampSchema):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RouteWithCustomers(RouteResponse):
    customers: List["CustomerResponse"] = []


class RouteListResponse(BaseModel):
    routes: List[RouteResponse]
    total: int


# =============================================================================
# PRODUCTION REPORT SCHEMAS
# =============================================================================

class ProductQuantity(BaseModel):
    product_id: int
    product_name: str
    category: Optional[str]
    unit: str
    total_quantity: int


class ProductionReportResponse(BaseModel):
    production_date: date
    products: List[ProductQuantity]
    total_orders: int
    total_customers: int
    generated_at: datetime


# =============================================================================
# DELIVERY LIST SCHEMAS
# =============================================================================

class DeliveryStop(BaseModel):
    order_id: int
    customer_id: int
    customer_name: str
    company_name: Optional[str]
    address: str
    latitude: Optional[float]
    longitude: Optional[float]
    delivery_window: dict
    delivery_instructions: Optional[str]
    phone: Optional[str]
    lines: List[dict]
    route_position: Optional[int]


class RouteDeliveryList(BaseModel):
    route_id: int
    route_name: str
    delivery_date: date
    stops: List[DeliveryStop]
    total_stops: int
```

---

## 5. SUSOFT API SERVICE (Oppdater app/services/susoft.py)

```python
# Legg til disse metodene i SuSoftService-klassen

    def get_all_customers(self, page_size: int = 100) -> List[Dict[str, Any]]:
        """Hent alle kunder fra Susoft med paginering."""
        all_customers = []
        page = 0
        
        while True:
            response = self.client.get(
                "/customer/list",
                params={"page": page, "pageSize": page_size},
                headers=self._get_headers()
            )
            
            if not response.is_success:
                raise SuSoftAPIError(
                    f"Failed to get customers: {response.status_code}",
                    response.status_code,
                    response.text
                )
            
            customers = response.json()
            if not customers:
                break
            
            all_customers.extend(customers)
            
            if len(customers) < page_size:
                break
            
            page += 1
        
        return all_customers

    def get_all_products(self, page_size: int = 100) -> List[Dict[str, Any]]:
        """Hent alle produkter fra Susoft med paginering."""
        all_products = []
        page = 0
        
        while True:
            response = self.client.get(
                "/product/list",
                params={"page": page, "pageSize": page_size},
                headers=self._get_headers()
            )
            
            if not response.is_success:
                raise SuSoftAPIError(
                    f"Failed to get products: {response.status_code}",
                    response.status_code,
                    response.text
                )
            
            products = response.json()
            if not products:
                break
            
            all_products.extend(products)
            
            if len(products) < page_size:
                break
            
            page += 1
        
        return all_products

    def create_order(self, order: "Order") -> str:
        """
        Opprett ordre i Susoft via POST /order.
        
        Returnerer Susoft sin ordre-ID.
        """
        # Bygg order payload basert på Susoft API spec
        order_lines = []
        for line in order.lines:
            order_lines.append({
                "productId": line.product.susoft_product_id,
                "quantity": line.quantity,
                "unitPrice": float(line.unit_price),
                "vatRate": float(line.vat_rate),
                "totalPrice": float(line.line_amount_incl_vat)
            })
        
        payload = {
            "customerId": order.customer.susoft_customer_id,
            "alternativeId": str(order.order_uuid),  # Vår ID for kobling
            "deliveryDate": order.delivery_date.isoformat(),
            "isForInvoicing": True,  # VIKTIG: Faktura-ordre
            "orderLines": order_lines,
            "description": f"Ordre fra Lampeland Bakeri Ordresystem - {order.delivery_date}"
        }
        
        response = self.client.post(
            "/order",
            json=payload,
            headers=self._get_headers()
        )
        
        # Logg til database
        self._log_sync(
            sync_type="order_create",
            entity_type="order",
            entity_id=order.id,
            method="POST",
            endpoint="/order",
            request_payload=payload,
            response_status=response.status_code,
            response_body=response.text,
            success=response.is_success
        )
        
        if not response.is_success:
            raise SuSoftAPIError(
                f"Failed to create order: {response.status_code}",
                response.status_code,
                response.text
            )
        
        result = response.json()
        return str(result.get("id") or result.get("orderNo"))

    def update_order(self, order: "Order") -> bool:
        """
        Oppdater eksisterende ordre i Susoft via PUT /order/{id}.
        
        Returnerer True hvis vellykket.
        """
        # Bygg oppdatert payload
        order_lines = []
        for line in order.lines:
            order_lines.append({
                "productId": line.product.susoft_product_id,
                "quantity": line.quantity,
                "unitPrice": float(line.unit_price),
                "vatRate": float(line.vat_rate),
                "totalPrice": float(line.line_amount_incl_vat)
            })
        
        payload = {
            "id": int(order.susoft_order_id),
            "customerId": order.customer.susoft_customer_id,
            "alternativeId": str(order.order_uuid),
            "deliveryDate": order.delivery_date.isoformat(),
            "isForInvoicing": True,
            "orderLines": order_lines
        }
        
        response = self.client.put(
            f"/order/{order.susoft_order_id}",
            json=payload,
            headers=self._get_headers()
        )
        
        # Logg til database
        self._log_sync(
            sync_type="order_update",
            entity_type="order",
            entity_id=order.id,
            method="PUT",
            endpoint=f"/order/{order.susoft_order_id}",
            request_payload=payload,
            response_status=response.status_code,
            response_body=response.text,
            success=response.is_success
        )
        
        if not response.is_success:
            raise SuSoftAPIError(
                f"Failed to update order: {response.status_code}",
                response.status_code,
                response.text
            )
        
        return True
```

---

## 6. CELERY TASKS (Oppdater app/tasks.py)

```python
# Legg til disse tasks i app/tasks.py

@celery_app.task(name="app.tasks.generate_orders_for_customer")
def generate_orders_for_customer(customer_id: int):
    """
    Generer ordrer for en spesifikk kunde basert på deres rolling window.
    
    Logikk:
    1. Hent kundens aktive MasterTemplate
    2. For hver dag i rolling_window frem i tid:
       a. Sjekk om dato er sperret (holiday eller customer blocked)
       b. Sjekk om det finnes en OrderDateOverride
       c. Sjekk om orden allerede eksisterer
       d. Hvis ikke, opprett ordre fra template
    3. Send nye ordrer til Susoft
    """
    from .models import (
        Customer, MasterTemplate, MasterTemplateItem, Order, OrderLine,
        Holiday, CustomerBlockedDate, OrderDateOverride, OrderStatus, SyncStatus
    )
    from .api.pricing import get_effective_price
    
    db = SessionLocal()
    try:
        customer = db.get(Customer, customer_id)
        if not customer or not customer.is_active:
            return {"error": "Customer not found or inactive"}
        
        # Hent aktiv mal
        template = db.execute(
            select(MasterTemplate)
            .where(
                MasterTemplate.customer_id == customer_id,
                MasterTemplate.is_active == True
            )
            .options(selectinload(MasterTemplate.items))
        ).scalar_one_or_none()
        
        if not template:
            return {"error": "No active template for customer"}
        
        today = date.today()
        end_date = today + timedelta(days=customer.order_lead_days)
        
        orders_created = 0
        
        # Iterer gjennom alle dager i vinduet
        current_date = today + timedelta(days=1)  # Start fra i morgen
        while current_date <= end_date:
            # Sjekk om dato er sperret
            if is_blocked_date(db, customer_id, current_date):
                current_date += timedelta(days=1)
                continue
            
            # Sjekk om ordre allerede finnes
            existing = db.execute(
                select(Order).where(
                    Order.customer_id == customer_id,
                    Order.delivery_date == current_date,
                    Order.is_deleted == False
                )
            ).scalar_one_or_none()
            
            if existing:
                current_date += timedelta(days=1)
                continue
            
            # Finn template items for denne ukedagen
            day_of_week = current_date.isoweekday()  # 1=Monday, 7=Sunday
            template_items = [
                item for item in template.items 
                if item.day_of_week == day_of_week and item.quantity > 0
            ]
            
            if not template_items:
                current_date += timedelta(days=1)
                continue
            
            # Opprett ordre
            order = Order(
                customer_id=customer_id,
                delivery_date=current_date,
                status=OrderStatus.DRAFT,
                sync_status=SyncStatus.PENDING,
                generated_from_template_id=template.id
            )
            db.add(order)
            db.flush()  # Få ID
            
            # Legg til ordrelinjer
            for item in template_items:
                # Sjekk for override
                override = db.execute(
                    select(OrderDateOverride).where(
                        OrderDateOverride.customer_id == customer_id,
                        OrderDateOverride.product_id == item.product_id,
                        OrderDateOverride.override_date == current_date
                    )
                ).scalar_one_or_none()
                
                quantity = override.quantity if override else item.quantity
                
                if quantity <= 0:
                    continue
                
                # Hent pris
                price_info = get_effective_price(
                    db, customer_id, item.product_id, current_date
                )
                
                line = OrderLine(
                    order_id=order.id,
                    product_id=item.product_id,
                    quantity=quantity,
                    unit_price=price_info["price"],
                    vat_rate=price_info["vat_rate"],
                    line_amount_excl_vat=price_info["price"] * quantity,
                    line_vat=price_info["price"] * quantity * (price_info["vat_rate"] / 100),
                    line_amount_incl_vat=price_info["price"] * quantity * (1 + price_info["vat_rate"] / 100)
                )
                db.add(line)
            
            orders_created += 1
            current_date += timedelta(days=1)
        
        db.commit()
        
        return {"customer_id": customer_id, "orders_created": orders_created}
        
    finally:
        db.close()


@celery_app.task(name="app.tasks.sync_pending_orders")
def sync_pending_orders():
    """
    Synkroniser alle ventende ordrer til Susoft.
    
    Kjører hver time.
    """
    from .services.susoft import SuSoftService, SuSoftAPIError
    
    db = SessionLocal()
    try:
        # Hent ordrer som skal synkes
        # (Pending, og delivery_date er innenfor synk-vinduet)
        sync_window = date.today() + timedelta(days=2)  # Synk 2 dager før levering
        
        orders = db.execute(
            select(Order)
            .where(
                Order.sync_status == SyncStatus.PENDING,
                Order.delivery_date <= sync_window,
                Order.is_deleted == False
            )
            .options(
                selectinload(Order.customer),
                selectinload(Order.lines).selectinload(OrderLine.product)
            )
        ).scalars().all()
        
        service = SuSoftService(db)
        
        synced = 0
        failed = 0
        
        for order in orders:
            try:
                susoft_id = service.create_order(order)
                order.susoft_order_id = susoft_id
                order.sync_status = SyncStatus.SYNCED
                order.last_sync_attempt = datetime.utcnow()
                synced += 1
            except SuSoftAPIError as e:
                order.sync_status = SyncStatus.FAILED
                order.last_sync_attempt = datetime.utcnow()
                order.sync_error_message = str(e)
                order.sync_retry_count += 1
                failed += 1
        
        db.commit()
        
        return {"synced": synced, "failed": failed}
        
    finally:
        db.close()


@celery_app.task(name="app.tasks.generate_production_report")
def generate_production_report(target_date: date):
    """
    Generer aggregert produksjonsrapport for en dato.
    
    Kjøres automatisk når ordrer låses (kl 15:00 dagen før).
    """
    from sqlalchemy import func
    
    db = SessionLocal()
    try:
        # Aggreger produkter
        results = db.execute(
            select(
                Product.id,
                Product.name,
                Product.category,
                Product.unit,
                func.sum(OrderLine.quantity).label("total")
            )
            .join(OrderLine)
            .join(Order)
            .where(
                Order.delivery_date == target_date,
                Order.is_deleted == False,
                Order.status != OrderStatus.CANCELLED
            )
            .group_by(Product.id)
        ).all()
        
        product_totals = [
            {
                "product_id": r.id,
                "product_name": r.name,
                "category": r.category,
                "unit": r.unit,
                "total_quantity": r.total
            }
            for r in results
        ]
        
        # Tell ordrer og kunder
        orders = db.execute(
            select(Order)
            .where(
                Order.delivery_date == target_date,
                Order.is_deleted == False,
                Order.status != OrderStatus.CANCELLED
            )
        ).scalars().all()
        
        summary = DailyProductionSummary(
            production_date=target_date,
            product_totals=product_totals,
            total_orders=len(orders),
            total_customers=len(set(o.customer_id for o in orders)),
            total_order_lines=sum(len(o.lines) for o in orders)
        )
        
        db.add(summary)
        db.commit()
        
        return {"date": str(target_date), "products": len(product_totals)}
        
    finally:
        db.close()
```

---

## 7. FRONTEND KOMPONENTER

### 7.1 Routes Page (Ny fil: frontend/src/pages/Routes.jsx)
```jsx
import { useState, useEffect } from 'react';

const API_BASE = 'http://localhost:8000/api/v1';

export default function Routes() {
  const [routes, setRoutes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    delivery_days: [1, 2, 3, 4, 5],
    is_active: true
  });

  useEffect(() => {
    fetchRoutes();
  }, []);

  const fetchRoutes = async () => {
    try {
      const res = await fetch(`${API_BASE}/routes`);
      const data = await res.json();
      setRoutes(data.routes || []);
    } catch (err) {
      console.error('Failed to fetch routes:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/routes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });
      if (res.ok) {
        fetchRoutes();
        setShowForm(false);
        setFormData({ name: '', description: '', delivery_days: [1, 2, 3, 4, 5], is_active: true });
      }
    } catch (err) {
      console.error('Failed to create route:', err);
    }
  };

  const dayNames = ['Man', 'Tir', 'Ons', 'Tor', 'Fre', 'Lør', 'Søn'];

  if (loading) return <div className="p-4">Laster ruter...</div>;

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Leveringsruter</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
        >
          {showForm ? 'Avbryt' : '+ Ny rute'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="bg-white p-6 rounded-lg shadow mb-6">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Rutenavn</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({...formData, name: e.target.value})}
                className="w-full border rounded px-3 py-2"
                placeholder="F.eks. Rute 1 - Kongsberg"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Beskrivelse</label>
              <input
                type="text"
                value={formData.description}
                onChange={(e) => setFormData({...formData, description: e.target.value})}
                className="w-full border rounded px-3 py-2"
                placeholder="Valgfri beskrivelse"
              />
            </div>
          </div>
          <div className="mt-4">
            <label className="block text-sm font-medium mb-2">Leveringsdager</label>
            <div className="flex gap-2">
              {dayNames.map((day, idx) => (
                <label key={idx} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={formData.delivery_days.includes(idx + 1)}
                    onChange={(e) => {
                      const dayNum = idx + 1;
                      const days = e.target.checked
                        ? [...formData.delivery_days, dayNum]
                        : formData.delivery_days.filter(d => d !== dayNum);
                      setFormData({...formData, delivery_days: days.sort()});
                    }}
                  />
                  {day}
                </label>
              ))}
            </div>
          </div>
          <button type="submit" className="mt-4 bg-green-600 text-white px-4 py-2 rounded">
            Lagre rute
          </button>
        </form>
      )}

      <div className="grid gap-4">
        {routes.map(route => (
          <div key={route.id} className="bg-white p-4 rounded-lg shadow">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-bold text-lg">{route.name}</h3>
                {route.description && <p className="text-gray-600">{route.description}</p>}
                <div className="mt-2 flex gap-1">
                  {route.delivery_days.map(d => (
                    <span key={d} className="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">
                      {dayNames[d - 1]}
                    </span>
                  ))}
                </div>
              </div>
              <span className={`px-2 py-1 rounded text-sm ${route.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                {route.is_active ? 'Aktiv' : 'Inaktiv'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

### 7.2 Production Report Page (Ny fil: frontend/src/pages/ProductionReport.jsx)
```jsx
import { useState, useEffect } from 'react';

const API_BASE = 'http://localhost:8000/api/v1';

export default function ProductionReport() {
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchReport = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/reports/production/${selectedDate}`);
      if (res.ok) {
        const data = await res.json();
        setReport(data);
      }
    } catch (err) {
      console.error('Failed to fetch report:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReport();
  }, [selectedDate]);

  // Grupper produkter etter kategori
  const groupedProducts = report?.products?.reduce((acc, product) => {
    const category = product.category || 'Ukategorisert';
    if (!acc[category]) acc[category] = [];
    acc[category].push(product);
    return acc;
  }, {}) || {};

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Produksjonsrapport</h1>
        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="border rounded px-3 py-2"
        />
      </div>

      {loading && <div>Laster rapport...</div>}

      {report && !loading && (
        <>
          {/* Sammendrag */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-blue-50 p-4 rounded-lg">
              <div className="text-3xl font-bold text-blue-700">{report.total_orders}</div>
              <div className="text-sm text-blue-600">Ordrer</div>
            </div>
            <div className="bg-green-50 p-4 rounded-lg">
              <div className="text-3xl font-bold text-green-700">{report.total_customers}</div>
              <div className="text-sm text-green-600">Kunder</div>
            </div>
            <div className="bg-purple-50 p-4 rounded-lg">
              <div className="text-3xl font-bold text-purple-700">{report.products?.length || 0}</div>
              <div className="text-sm text-purple-600">Produkter</div>
            </div>
          </div>

          {/* Produktliste gruppert på kategori */}
          <div className="bg-white rounded-lg shadow">
            <div className="p-4 border-b bg-gray-50">
              <h2 className="font-bold">Produkter å produsere</h2>
            </div>
            
            {Object.entries(groupedProducts).map(([category, products]) => (
              <div key={category} className="border-b last:border-b-0">
                <div className="bg-gray-100 px-4 py-2 font-semibold text-gray-700">
                  {category}
                </div>
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-sm text-gray-500">
                      <th className="px-4 py-2">Produkt</th>
                      <th className="px-4 py-2 text-right">Antall</th>
                      <th className="px-4 py-2">Enhet</th>
                    </tr>
                  </thead>
                  <tbody>
                    {products.map(product => (
                      <tr key={product.product_id} className="border-t">
                        <td className="px-4 py-3">{product.product_name}</td>
                        <td className="px-4 py-3 text-right font-mono text-lg font-bold">
                          {product.total_quantity}
                        </td>
                        <td className="px-4 py-3 text-gray-500">{product.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>

          {/* Print-knapp */}
          <div className="mt-4 flex gap-2">
            <button
              onClick={() => window.print()}
              className="bg-gray-600 text-white px-4 py-2 rounded hover:bg-gray-700"
            >
              🖨️ Skriv ut
            </button>
          </div>
        </>
      )}
    </div>
  );
}
```

### 7.3 Delivery List Page (Ny fil: frontend/src/pages/DeliveryList.jsx)
```jsx
import { useState, useEffect } from 'react';

const API_BASE = 'http://localhost:8000/api/v1';

export default function DeliveryList() {
  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState('');
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [deliveryList, setDeliveryList] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchRoutes();
  }, []);

  const fetchRoutes = async () => {
    try {
      const res = await fetch(`${API_BASE}/routes`);
      const data = await res.json();
      setRoutes(data.routes || []);
    } catch (err) {
      console.error('Failed to fetch routes:', err);
    }
  };

  const fetchDeliveryList = async () => {
    if (!selectedRoute) return;
    setLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/reports/delivery-list/${selectedRoute}/${selectedDate}`
      );
      if (res.ok) {
        const data = await res.json();
        setDeliveryList(data);
      }
    } catch (err) {
      console.error('Failed to fetch delivery list:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (selectedRoute) {
      fetchDeliveryList();
    }
  }, [selectedRoute, selectedDate]);

  const openGoogleMaps = async () => {
    try {
      const res = await fetch(
        `${API_BASE}/reports/delivery-list/${selectedRoute}/${selectedDate}/google-maps-url`
      );
      if (res.ok) {
        const data = await res.json();
        window.open(data.url, '_blank');
      }
    } catch (err) {
      console.error('Failed to get Google Maps URL:', err);
    }
  };

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Kjøreliste</h1>

      {/* Velgere */}
      <div className="flex gap-4 mb-6">
        <select
          value={selectedRoute}
          onChange={(e) => setSelectedRoute(e.target.value)}
          className="border rounded px-3 py-2"
        >
          <option value="">Velg rute...</option>
          {routes.map(route => (
            <option key={route.id} value={route.id}>{route.name}</option>
          ))}
        </select>
        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="border rounded px-3 py-2"
        />
        {selectedRoute && (
          <button
            onClick={openGoogleMaps}
            className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700"
          >
            🗺️ Åpne i Google Maps
          </button>
        )}
      </div>

      {loading && <div>Laster kjøreliste...</div>}

      {deliveryList && !loading && (
        <div className="space-y-4">
          <div className="bg-blue-50 p-4 rounded-lg">
            <div className="font-bold">{deliveryList.route_name}</div>
            <div className="text-sm text-gray-600">
              {deliveryList.total_stops} stopp | {selectedDate}
            </div>
          </div>

          {deliveryList.stops.map((stop, idx) => (
            <div key={stop.order_id} className="bg-white rounded-lg shadow p-4">
              <div className="flex justify-between items-start mb-2">
                <div>
                  <span className="bg-blue-600 text-white w-8 h-8 rounded-full inline-flex items-center justify-center mr-2">
                    {idx + 1}
                  </span>
                  <span className="font-bold">{stop.customer_name}</span>
                  {stop.company_name && (
                    <span className="text-gray-500 ml-2">({stop.company_name})</span>
                  )}
                </div>
                {stop.phone && (
                  <a href={`tel:${stop.phone}`} className="text-blue-600">
                    📞 {stop.phone}
                  </a>
                )}
              </div>
              
              <div className="text-gray-600 mb-2">
                📍 {stop.address}
              </div>

              {stop.delivery_instructions && (
                <div className="text-sm bg-yellow-50 p-2 rounded mb-2">
                  💡 {stop.delivery_instructions}
                </div>
              )}

              <div className="border-t pt-2 mt-2">
                <table className="w-full text-sm">
                  <tbody>
                    {stop.lines.map((line, lineIdx) => (
                      <tr key={lineIdx}>
                        <td className="py-1">{line.product_name}</td>
                        <td className="py-1 text-right font-bold">{line.quantity}</td>
                        <td className="py-1 text-gray-500 w-12">{line.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

### 7.4 Oppdater App.jsx med nye ruter
```jsx
// Oppdater frontend/src/App.jsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Products from './pages/Products';
import Customers from './pages/Customers';
import Orders from './pages/Orders';
import NewOrder from './pages/NewOrder';
import Templates from './pages/Templates';
import Settings from './pages/Settings';
import RoutesPage from './pages/Routes';
import ProductionReport from './pages/ProductionReport';
import DeliveryList from './pages/DeliveryList';
import './index.css';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path='/' element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path='produkter' element={<Products />} />
          <Route path='kunder' element={<Customers />} />
          <Route path='bestillinger' element={<Orders />} />
          <Route path='bestillinger/ny' element={<NewOrder />} />
          <Route path='maler' element={<Templates />} />
          <Route path='ruter' element={<RoutesPage />} />
          <Route path='produksjon' element={<ProductionReport />} />
          <Route path='kjoreliste' element={<DeliveryList />} />
          <Route path='innstillinger' element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
```

---

## 8. ENVIRONMENT VARIABLES (.env)

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/lampeland_bakeri
# For utvikling:
# DATABASE_URL=sqlite:///./lampeland_bakeri.db

# Redis (for Celery)
REDIS_URL=redis://localhost:6379/0

# Susoft API
SUSOFT_BASE_URL=https://api.susoft.com:4443
SUSOFT_USERNAME=your_username
SUSOFT_PASSWORD=your_password
SUSOFT_SHOP_URL_KEY=your_shop_key
SUSOFT_TIMEOUT=30

# Google Maps API (for ruteoptimalisering)
GOOGLE_MAPS_API_KEY=your_api_key

# App settings
SECRET_KEY=your-secret-key-here
DEBUG=true
CUTOFF_HOUR=15
```

---

## 9. MIGRERING OG OPPSTART

```bash
# 1. Installer avhengigheter
pip install -r requirements.txt
cd frontend && npm install

# 2. Start database (SQLite for utvikling)
# Tabeller opprettes automatisk ved oppstart

# 3. Start Redis (for Celery)
docker run -d -p 6379:6379 redis:alpine

# 4. Start backend
uvicorn app.main:app --reload --port 8000

# 5. Start Celery worker
celery -A app.tasks worker --loglevel=info

# 6. Start Celery beat (scheduler)
celery -A app.tasks beat --loglevel=info

# 7. Start frontend
cd frontend && npm run dev
```

---

## 10. VIKTIGE FORRETNINGSREGLER

1. **Ordregenerering**: Ordrer genereres automatisk basert på `order_lead_days` per kunde (14-60 dager)

2. **Susoft-sync**: Ordrer sendes til Susoft 48 timer før levering med `isForInvoicing: true`

3. **Cutoff-tid**: Kl 15:00 dagen før levering låses ordrer for endringer

4. **Priser**: 
   - Standardpris hentes fra Susoft
   - Kundepriser i `CustomerProductPrice` overstyrer automatisk
   - Kundepriser synkes IKKE tilbake til Susoft (unidirectional)

5. **Stengte dager**: Sjekkes mot `holidays` og `customer_blocked_dates` tabellene

6. **Endringer etter sync**: Bruker PUT /order/{id} til Susoft for å oppdatere

---

*Dokument sist oppdatert: 2026-04-20*

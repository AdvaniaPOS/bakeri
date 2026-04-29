# Lampeland Bakeri - Ordresystem

B2B Order Management System for Lampeland Bakeri, integrated with SuSoft POS API.

## Architecture Overview

```
app/
├── __init__.py
├── main.py              # FastAPI application entry point
├── database.py          # SQLAlchemy configuration
├── models.py            # Database models (SQLAlchemy)
├── schemas.py           # Pydantic schemas for API validation
├── tasks.py             # Celery scheduled tasks
├── api/
│   ├── __init__.py
│   ├── customers.py     # Customer CRUD endpoints
│   ├── products.py      # Product CRUD endpoints
│   ├── pricing.py       # Customer-specific pricing with date logic
│   ├── templates.py     # Master template (Order Matrix) endpoints
│   ├── orders.py        # Order management endpoints
│   └── admin.py         # Admin functions (panic button, holidays, alerts)
└── services/
    ├── __init__.py
    └── susoft.py        # SuSoft POS API integration
```

## Database Schema

### Core Entities

| Model | Purpose |
|-------|---------|
| `Customer` | Mirrored from SuSoft, includes delivery windows and order lead time |
| `Product` | Mirrored from SuSoft, includes default pricing |
| `CustomerProductPrice` | Customer-specific pricing with `effective_from_date` |
| `MasterTemplate` | 7-day recurring order template per customer |
| `MasterTemplateItem` | Product/day/quantity entries in template |
| `Order` | Actual orders with SuSoft sync tracking |
| `OrderLine` | Order line items with captured prices |
| `OrderDateOverride` | Ad-hoc quantity overrides for specific dates |

### Supporting Entities

| Model | Purpose |
|-------|---------|
| `Holiday` | Norwegian public holidays (quantity = 0) |
| `CustomerBlockedDate` | Customer-specific blocked date ranges |
| `DeliveryRoute` | Google Maps optimized routes |
| `DeliveryIssue` | Driver-reported discrepancies |
| `AuditLog` | Full audit trail with required deletion reasons |
| `SyncLog` | SuSoft API sync attempt logs |
| `AdminAlert` | System alerts with email notifications |
| `User` | System users (admin, coordinator, driver) |

## Key Features

### 1. Price-Date Logic

The `CustomerProductPrice` table enables scheduled price changes:

```python
# Query: Get effective price for customer/product on a date
price_entry = db.execute(
    select(CustomerProductPrice)
    .where(
        CustomerProductPrice.customer_id == customer_id,
        CustomerProductPrice.product_id == product_id,
        CustomerProductPrice.effective_from_date <= target_date
    )
    .order_by(CustomerProductPrice.effective_from_date.desc())
    .limit(1)
).scalar_one_or_none()
```

When a price changes:
1. All future orders in DB are updated
2. Orders already sent to SuSoft are marked for re-sync
3. Audit trail is created

### 2. Order Matrix (Master Template)

Each customer has an active template with a 7-day grid:

```json
{
  "product_id": 1,
  "day_of_week": 1,  // Monday
  "quantity": 10
}
```

Orders are generated 14-30 days in advance (configurable per customer).

### 3. SuSoft Synchronization

- Orders marked with `sync_status` (pending, synced, failed)
- `susoft_order_id` for tracking in SuSoft
- Retry logic: every 60 mins, or next morning
- Admin alerts on persistent failures

### 4. Cut-off Time

All changes locked at 15:00 the day before delivery:

```python
cutoff_datetime = datetime.combine(
    delivery_date - timedelta(days=1),
    time(hour=15, minute=0)
)
```

### 5. Panic Button

Batch cancel all orders for a specific date:

```http
POST /api/v1/admin/panic-cancel
{
  "target_date": "2024-12-24",
  "reason": "Power outage at bakery"
}
```

## API Endpoints

### Customers
- `GET /api/v1/customers` - List customers
- `POST /api/v1/customers` - Create customer
- `GET /api/v1/customers/{id}` - Get customer
- `PATCH /api/v1/customers/{id}` - Update customer
- `DELETE /api/v1/customers/{id}` - Soft delete (requires reason)

### Products
- `GET /api/v1/products` - List products
- `POST /api/v1/products` - Create product
- `GET /api/v1/products/{id}` - Get product
- `PATCH /api/v1/products/{id}` - Update product
- `DELETE /api/v1/products/{id}` - Soft delete (requires reason)

### Pricing
- `POST /api/v1/pricing/lookup` - Get effective price for customer/product/date
- `GET /api/v1/pricing` - List customer prices
- `POST /api/v1/pricing` - Create price entry
- `PATCH /api/v1/pricing/{id}` - Update price (triggers order updates)
- `POST /api/v1/pricing/propagate` - Force price propagation to orders

### Templates
- `GET /api/v1/templates` - List templates
- `GET /api/v1/templates/{id}/matrix` - Get matrix view for UI
- `PUT /api/v1/templates/{id}/matrix` - Bulk update from matrix
- `POST /api/v1/templates/{id}/duplicate` - Copy template

### Orders
- `GET /api/v1/orders` - List orders with filters
- `GET /api/v1/orders/by-date/{date}` - Orders for driver view
- `POST /api/v1/orders` - Create manual order
- `PATCH /api/v1/orders/{id}/lines/{line_id}` - Ad-hoc quantity change
- `POST /api/v1/orders/{id}/confirm` - Confirm and schedule sync
- `POST /api/v1/orders/generate-from-template` - Generate from template

### Admin
- `POST /api/v1/admin/panic-cancel` - Emergency batch cancel
- `GET /api/v1/admin/holidays` - List holidays
- `POST /api/v1/admin/holidays/populate-norwegian/{year}` - Add Norwegian holidays
- `GET /api/v1/admin/blocked-dates` - Customer blocked dates
- `GET /api/v1/admin/alerts` - System alerts
- `GET /api/v1/admin/audit-logs` - Audit trail

## Celery Scheduled Tasks

| Task | Schedule | Purpose |
|------|----------|---------|
| `generate_orders_for_all_customers` | 02:00 daily | Generate orders from templates |
| `sync_pending_orders` | Every hour | Sync to SuSoft |
| `apply_cutoff_locks` | 15:00 daily | Lock next-day orders |
| `retry_failed_syncs` | 06:00 daily | Morning retry for failed syncs |
| `sync_from_susoft` | 01:00 daily | Pull customer/product data |
| `process_scheduled_price_changes` | 00:05 daily | Apply price changes |

## Setup

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Redis (for Celery)

### Installation

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your settings
```

### Environment Variables

```env
DATABASE_URL=postgresql://user:pass@localhost:5432/lampeland_bakeri
REDIS_URL=redis://localhost:6379/0
SUSOFT_BASE_URL=https://api.susoft.no
SUSOFT_API_KEY=your_api_key
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@lampeland-bakeri.no
SMTP_PASS=your_smtp_password
```

### Run

```bash
# Start API server
uvicorn app.main:app --reload

# Start Celery worker
celery -A app.tasks worker --loglevel=info

# Start Celery beat (scheduler)
celery -A app.tasks beat --loglevel=info
```

## Next Steps

1. **SuSoft Integration**: Update `services/susoft.py` with actual SuSoft API endpoints from their Swagger spec
2. **Google Maps Integration**: Add route optimization service
3. **Driver Portal**: Create mobile-friendly delivery view
4. **PDF Generation**: Implement driving plans and Zebra labels
5. **Authentication**: Add proper user authentication (OAuth, Azure AD)
6. **Frontend**: Build admin UI (React/Vue recommended)

## License

Proprietary - Lampeland Bakeri

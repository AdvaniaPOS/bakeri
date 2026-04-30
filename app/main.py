"""
Lampeland Bakeri - Ordresystem
B2B Order Management System integrated with SuSoft POS

Multi-tenant SaaS application for bakery order management.
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .logging_config import setup_logging
from .middleware import TenantContextMiddleware
from .rate_limit import RateLimitMiddleware
from .api import customers, products, pricing, templates, orders, admin, routes, reports, susoft_sync, auth, overrides, production


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup: structured logging + database
    setup_logging(
        level=os.getenv("LOG_LEVEL", "INFO"),
        json_output=os.getenv("LOG_JSON", "0") == "1",
    )
    init_db()

    # Startup: ensure horizon for all active tenants (best-effort, non-blocking).
    # Dette dekker scenariet hvor ingen logger inn på en stund — den daglige
    # Celery-jobben er kanskje ikke kjørende i dev/local, så vi tar det selv.
    import asyncio
    import logging
    log = logging.getLogger(__name__)

    async def _startup_horizon_check():
        try:
            from .database import SessionLocal
            from .auth_models import Tenant
            from .api.orders import _run_ensure_horizon
            from sqlalchemy import select

            db = SessionLocal()
            try:
                tenant_ids = db.execute(
                    select(Tenant.id).where(
                        Tenant.is_active == True,
                        Tenant.is_deleted == False,
                    )
                ).scalars().all()
            finally:
                db.close()

            log.info("startup horizon check: %d active tenants", len(tenant_ids))
            for tid in tenant_ids:
                # Kjør i thread så vi ikke blokkerer event-loopen.
                await asyncio.to_thread(_run_ensure_horizon, tid)
        except Exception as exc:
            log.warning("startup horizon check failed: %s", exc)

    # Fire-and-forget — ikke blokker oppstart.
    asyncio.create_task(_startup_horizon_check())

    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="Bakeri Ordresystem - Multi-Tenant SaaS",
    description="""
    Multi-tenant B2B Order Management System for bakeries.
    
    ## Multi-Tenant Architecture
    
    - **Tenant Isolation**: Each bakery chain has fully isolated data
    - **Role-based Access**: SUPER_ADMIN, TENANT_ADMIN, MANAGER, DRIVER, VIEWER
    - **JWT Authentication**: Secure token-based authentication
    - **API Key Support**: Programmatic access for integrations
    
    ## Features
    
    - **Customer & Product Management**: Mirror data from SuSoft POS
    - **Customer-specific Pricing**: Schedule price changes with automatic order updates
    - **Order Matrix**: 7-day template per customer for recurring orders
    - **Order Generation**: Auto-generate orders 14-30 days in advance
    - **Ad-hoc Changes**: Override quantities without breaking templates
    - **Cut-off Time**: Lock orders at 15:00 day before delivery
    - **Holiday Handling**: Automatic zero quantity for holidays
    - **SuSoft Sync**: Reliable sync with retry logic
    - **Audit Trail**: Full tracking of all changes
    - **Panic Button**: Emergency batch cancel functionality
    """,
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
# Configure CORS_ALLOW_ORIGINS as comma-separated list in production, e.g.
#   CORS_ALLOW_ORIGINS="https://app.lampeland.no,https://admin.lampeland.no"
# In dev (default) we allow Vite + common localhost origins.
_cors_env = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    _cors_regex = None
else:
    _cors_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    _cors_regex = r"^http://(localhost|127\.0\.0\.1):\d+$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-API-Key"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# Rate limiting (per-tenant). Added BEFORE TenantContextMiddleware so the
# 429 response still benefits from request-id, but auth parsing happens here too.
app.add_middleware(RateLimitMiddleware)

# Populate logging context (tenant_id, user_id, request_id) for every request.
app.add_middleware(TenantContextMiddleware)

# Include routers
app.include_router(auth.router, prefix="/api/v1")  # Auth endpoints (no authentication required)
app.include_router(customers.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
app.include_router(pricing.router, prefix="/api/v1")
app.include_router(templates.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(routes.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(susoft_sync.router, prefix="/api/v1")
app.include_router(overrides.router, prefix="/api/v1")
app.include_router(production.router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Lampeland Bakeri - Ordresystem",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

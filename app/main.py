"""
Lampeland Bakeri - Ordresystem
B2B Order Management System integrated with SuSoft POS

Multi-tenant SaaS application for bakery order management.
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .database import init_db
from .logging_config import setup_logging
from .middleware import TenantContextMiddleware, SecurityHeadersMiddleware
from .rate_limit import RateLimitMiddleware
from .api import customers, products, pricing, templates, orders, admin, routes, reports, susoft_sync, auth, overrides, production, driver, portal, notifications

# Sentry: initieres tidlig (før app-bygging) hvis DSN er satt.
# Sett SENTRY_DSN i .env. Tom verdi = deaktivert.
_SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("APP_ENV", "production"),
            release=os.getenv("APP_RELEASE", "unknown"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.0")),
            send_default_pii=False,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        )
    except Exception as _exc:  # pragma: no cover
        import logging as _l
        _l.getLogger(__name__).warning("Sentry init feilet: %s", _exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup: structured logging + database
    setup_logging(
        level=os.getenv("LOG_LEVEL", "INFO"),
        json_output=os.getenv("LOG_JSON", "0") == "1",
    )
    init_db()

    # Auto-migrer skjema (legg til manglende kolonner + backfill defaults)
    # slik at vi aldri får 500-feil pga manglende kolonner etter en deploy.
    # Kan deaktiveres ved AUTO_MIGRATE=0 (hvis man kjører Alembic separat).
    if os.getenv("AUTO_MIGRATE", "1") != "0":
        try:
            from .auto_migrate import sync_schema
            from .database import engine
            result = sync_schema(engine)
            if result["added"] or result["backfilled"]:
                import logging as _logging
                _logging.getLogger(__name__).info(
                    "auto_migrate: added=%s backfilled=%s",
                    result["added"], result["backfilled"],
                )
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).error("auto_migrate failed: %s", exc, exc_info=True)

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
    - **Cut-off Time**: Lock orders at 10:00 day before delivery
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
_app_env = os.getenv("APP_ENV", "development").lower()
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    _cors_regex = None
else:
    if _app_env == "production":
        # Hard-fail i produksjon: vi tillater ALDRI permissive defaults i prod.
        # Sett CORS_ALLOW_ORIGINS i .env / systemd-environment før (re)start.
        raise RuntimeError(
            "CORS_ALLOW_ORIGINS er ikke satt, men APP_ENV=production. "
            "Sett eksplisitt liste over tillatte origins (kommaseparert) "
            "for å unngå å åpne API-et for vilkårlige nettsteder."
        )
    _cors_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    _cors_regex = r"^http://(localhost|127\.0\.0\.1):\d+$"

# TrustedHostMiddleware: blokkerer Host-header-angrep / DNS-rebinding.
# Sett TRUSTED_HOSTS som kommaseparert liste i prod, f.eks.
#   TRUSTED_HOSTS="bakeri.poshub.no,api.bakeri.poshub.no"
# I dev (default) tillates alt for å ikke knekke localhost/127.0.0.1/lan-IP.
_trusted_hosts_env = os.getenv("TRUSTED_HOSTS", "").strip()
if not _trusted_hosts_env and _app_env == "production":
    raise RuntimeError(
        "TRUSTED_HOSTS er ikke satt, men APP_ENV=production. "
        "Sett liste over gyldige Host-headers (kommaseparert) for å hindre "
        "Host-header / DNS-rebinding-angrep."
    )

# Middleware stack — Starlette wrapper i OMVENDT rekkefølge, så det som
# legges til SIST blir YTTERST og kjører FØRST på request, SIST på response.
# Ønsket request-flyt (ytterst → innerst):
#   TrustedHost → CORS → SecurityHeaders → RateLimit → TenantContext → route
# Det betyr at vi MÅ legge til i denne rekkefølgen (innerst først):

# Innerst: populer logging-kontekst (tenant_id, user_id, request_id).
app.add_middleware(TenantContextMiddleware)

# Rate limiting per tenant (parser auth selv).
app.add_middleware(RateLimitMiddleware)

# Sikkerhets-headers settes på ALLE responser (også 429/500/etc.).
app.add_middleware(SecurityHeadersMiddleware)

# CORS (preflight håndteres her).
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-API-Key"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# Ytterst: TrustedHost — avvis ugyldig Host-header umiddelbart.
if _trusted_hosts_env:
    _trusted_hosts = [h.strip() for h in _trusted_hosts_env.split(",") if h.strip()]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts)


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
app.include_router(driver.router, prefix="/api/v1")
app.include_router(portal.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Advania Bakeri - Ordresystem",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/health/detailed")
@app.get("/api/v1/health/detailed")
async def health_detailed():
    """
    Detaljert helsesjekk: database, e-post-konfig, Susoft (hvis aktivert).
    Brukes av status-side. Krever ingen autentisering, men returnerer
    minimal info for ikke å lekke detaljer.
    """
    from sqlalchemy import text
    from .database import SessionLocal

    result = {
        "status": "healthy",
        "checks": {},
    }

    # Database
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        result["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        result["checks"]["database"] = {"status": "error", "error": str(e)[:200]}
        result["status"] = "degraded"

    # E-post (Resend)
    if os.getenv("RESEND_API_KEY", "").strip():
        result["checks"]["email"] = {"status": "ok", "provider": "resend"}
    else:
        result["checks"]["email"] = {"status": "warning", "detail": "RESEND_API_KEY ikke satt — e-post går til logg"}

    # Sentry
    result["checks"]["sentry"] = {"status": "ok" if _SENTRY_DSN else "disabled"}

    return result

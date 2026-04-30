"""
Felles pytest-fixtures.

Vi setter DATABASE_URL FØR vi importerer app-moduler, slik at hver test-kjøring
kjører mot en isolert SQLite-fil i temp-katalog. Det unngår at testene rører
prod- eller dev-databasen.
"""
import os
import tempfile
from pathlib import Path

# VIKTIG: Må settes før noen test-modul importerer app.* — gjøres her på toppen
# slik at det skjer ved collection-tid (før test-modulene leses inn).
_TMP_DIR = Path(tempfile.mkdtemp(prefix="bakeri_test_"))
_DB_PATH = _TMP_DIR / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

import pytest


@pytest.fixture(scope="session", autouse=True)
def _setup_test_db():
    """Lag tabeller i den isolerte test-DB-en."""
    from app.database import Base, engine
    import app.models  # noqa: F401 — registrer alle modeller på Base
    import app.auth_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    yield
    try:
        _DB_PATH.unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture
def db_session():
    """Gir en frisk DB-sesjon pr test, ruller tilbake etter."""
    from app.database import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant(db_session):
    """Opprett en test-tenant."""
    from app.auth_models import Tenant
    t = Tenant(
        slug=f"test-{os.urandom(4).hex()}",
        name="Test Bakeri",
        email="test@example.com",
        is_active=True,
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def customer(db_session, tenant):
    """Opprett en testkunde."""
    from app.models import Customer
    c = Customer(
        tenant_id=tenant.id,
        name="Test Kunde AS",
        is_active=True,
        order_lead_days=14,
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


@pytest.fixture
def product(db_session, tenant):
    """Opprett et testprodukt."""
    from app.models import Product
    from decimal import Decimal
    p = Product(
        tenant_id=tenant.id,
        sku="TEST-001",
        name="Rundstykke",
        default_price=Decimal("12.00"),
        unit="stk",
        vat_rate=Decimal("15.00"),
        is_active=True,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


@pytest.fixture
def template_with_item(db_session, tenant, customer, product):
    """Aktiv mal som leverer 5 rundstykker hver tirsdag (day_of_week=2)."""
    from app.models import MasterTemplate, MasterTemplateItem
    tpl = MasterTemplate(
        tenant_id=tenant.id,
        customer_id=customer.id,
        is_active=True,
        name="Test mal",
    )
    db_session.add(tpl)
    db_session.flush()
    item = MasterTemplateItem(
        tenant_id=tenant.id,
        template_id=tpl.id,
        product_id=product.id,
        day_of_week=2,  # Tirsdag
        quantity=5,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(tpl)
    return tpl

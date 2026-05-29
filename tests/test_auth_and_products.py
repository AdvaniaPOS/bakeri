"""
Pytest-smoketester for autentisering og produktendpoint.

Disse kjører helt isolert mot temp-DB definert i `tests/conftest.py`.
Kjør med:  pytest tests/
"""
from __future__ import annotations

import bcrypt
import pytest
from fastapi.testclient import TestClient

from app.auth_models import SubscriptionPlan, SubscriptionStatus, Tenant, User, UserRole
from app.database import SessionLocal
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def admin_user(db_session, tenant):
    """Opprett en lokal tenant_admin med kjent passord."""
    pw = "test-password-123"
    user = User(
        tenant_id=tenant.id,
        email=f"admin-{tenant.id}@bakeri.local",
        password_hash=bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode(),
        first_name="Test",
        last_name="Admin",
        role=UserRole.TENANT_ADMIN,
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return {"user": user, "email": user.email, "password": pw}


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# --- Auth -----------------------------------------------------------------


def test_login_success(client, admin_user):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": admin_user["email"], "password": admin_user["password"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["user"]["email"] == admin_user["email"]


def test_login_wrong_password(client, admin_user):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": admin_user["email"], "password": "feil"},
    )
    assert r.status_code in (401, 503)  # 503 hvis Susoft-fallback prøver og feiler


def test_forgot_password_accepts_username_for_susoft_user(client, db_session, tenant):
    user = User(
        tenant_id=tenant.id,
        email="demo-user@susoft.local",
        password_hash="__susoft__",
        first_name="Demo",
        last_name="User",
        role=UserRole.TENANT_ADMIN,
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    db_session.commit()

    r = client.post("/api/v1/auth/forgot-password", json={"email": "demo-user"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert "SuSoft" in body["message"]

    db_session.refresh(user)
    assert user.password_reset_token is None


def test_unauthenticated_products_endpoint(client):
    r = client.get("/api/v1/products")
    assert r.status_code in (401, 403)


# --- Products -------------------------------------------------------------


def test_products_list_includes_production_fields(client, admin_user, product):
    token = _login(client, admin_user["email"], admin_user["password"])
    r = client.get(
        "/api/v1/products",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(p["id"] == product.id for p in items)
    p = next(p for p in items if p["id"] == product.id)
    # Produksjonsfelt skal være med (default-verdier)
    assert "batch_size" in p
    assert "production_lead_minutes" in p
    assert isinstance(p["batch_size"], int)
    assert isinstance(p["production_lead_minutes"], int)


def test_patch_product_batch_size(client, admin_user, product):
    token = _login(client, admin_user["email"], admin_user["password"])
    r = client.patch(
        f"/api/v1/products/{product.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"batch_size": 12, "production_step": "Ovn 1", "production_lead_minutes": 25},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["batch_size"] == 12
    assert body["production_step"] == "Ovn 1"
    assert body["production_lead_minutes"] == 25


def test_patch_product_active_marks_override(client, admin_user, product, db_session):
    token = _login(client, admin_user["email"], admin_user["password"])
    r = client.patch(
        f"/api/v1/products/{product.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )
    assert r.status_code == 200
    db_session.refresh(product)
    assert product.is_active is False
    assert product.is_active_overridden is True

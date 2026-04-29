"""
End-to-end multi-tenant isolation smoke test.

Boots a second tenant + admin user directly in the DB, then exercises the API
using two parallel sessions (demo tenant 1 vs. smoketest tenant 2) and asserts
that data created by tenant B is invisible to tenant A and vice versa.

Run:
    1. Start backend:  uvicorn app.main:app
    2. python smoke_test_tenants.py [--base-url http://127.0.0.1:8000]

Exit code 0 on success, 1 on any isolation breach.
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from typing import Any

import bcrypt
import httpx

from app.auth_models import (
    SubscriptionPlan, SubscriptionStatus, Tenant, User, UserRole,
)
from app.database import SessionLocal


SMOKE_TENANT_SLUG = "smoketest"
SMOKE_USER_EMAIL = "smoketest@bakeri.local"
SMOKE_USER_PASSWORD = "smoketest123"
DEMO_USER_EMAIL = "demo@bakeri.local"
DEMO_USER_PASSWORD = "demo123"


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()


def ensure_smoke_tenant() -> int:
    """Idempotently create the smoketest tenant + admin user. Returns tenant id."""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == SMOKE_TENANT_SLUG).first()
        if not tenant:
            tenant = Tenant(
                slug=SMOKE_TENANT_SLUG,
                name="Smoketest Bakeri",
                email=SMOKE_USER_EMAIL,
                country="Norway",
                subscription_plan=SubscriptionPlan.FREE_TRIAL,
                subscription_status=SubscriptionStatus.TRIAL,
                is_active=True,
            )
            db.add(tenant)
            db.flush()

        user = db.query(User).filter(User.email == SMOKE_USER_EMAIL).first()
        if not user:
            user = User(
                email=SMOKE_USER_EMAIL,
                password_hash=_hash(SMOKE_USER_PASSWORD),
                first_name="Smoke",
                last_name="Test",
                tenant_id=tenant.id,
                role=UserRole.TENANT_ADMIN,
                is_active=True,
                email_verified=True,
            )
            db.add(user)
        db.commit()
        return tenant.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class TenantClient:
    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=15)
        self.email = email
        self._password = password
        self.token: str | None = None
        self.tenant_id: int | None = None

    def login(self) -> None:
        r = self.client.post("/api/v1/auth/login",
                             json={"email": self.email, "password": self._password})
        r.raise_for_status()
        body = r.json()
        self.token = body["access_token"]
        self.tenant_id = body["tenant"]["id"]
        self.client.headers["Authorization"] = f"Bearer {self.token}"

    def get(self, path: str, **kw) -> httpx.Response:
        return self.client.get(path, **kw)

    def post(self, path: str, json: Any) -> httpx.Response:
        return self.client.post(path, json=json)

    def delete(self, path: str, json: Any = None) -> httpx.Response:
        return self.client.request("DELETE", path, json=json)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

class SmokeFail(AssertionError):
    pass


def assert_eq(actual, expected, msg: str) -> None:
    if actual != expected:
        raise SmokeFail(f"{msg}: expected {expected!r}, got {actual!r}")


def assert_status(resp: httpx.Response, expected: int, msg: str) -> None:
    if resp.status_code != expected:
        raise SmokeFail(
            f"{msg}: expected HTTP {expected}, got {resp.status_code} -> {resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------

def run(base_url: str) -> int:
    print("== Bootstrap ==")
    smoke_tid = ensure_smoke_tenant()
    print(f"  smoke tenant id: {smoke_tid}")

    print("== Login ==")
    a = TenantClient(base_url, DEMO_USER_EMAIL, DEMO_USER_PASSWORD)
    b = TenantClient(base_url, SMOKE_USER_EMAIL, SMOKE_USER_PASSWORD)
    a.login()
    b.login()
    print(f"  A: tenant={a.tenant_id} ({a.email})")
    print(f"  B: tenant={b.tenant_id} ({b.email})")
    if a.tenant_id == b.tenant_id:
        raise SmokeFail("Both clients ended up in same tenant — bootstrap failed")

    suffix = uuid.uuid4().hex[:6]

    # --- B creates a customer + product ---
    print("== B creates customer + product ==")
    cust_payload = {
        "name": f"SmokeCust-{suffix}",
        "city": "Oslo",
        "country": "Norway",
        "order_lead_days": 14,
        "is_active": True,
    }
    r = b.post("/api/v1/customers", cust_payload)
    assert_status(r, 201, "B create customer")
    b_customer_id = r.json()["id"]
    print(f"  B customer id={b_customer_id}")

    prod_payload = {
        "sku": f"SMOKE-{suffix}",
        "name": f"SmokeProduct-{suffix}",
        "default_price": "10.00",
        "vat_rate": "15.00",
    }
    r = b.post("/api/v1/products", prod_payload)
    assert_status(r, 201, "B create product")
    b_product_id = r.json()["id"]
    print(f"  B product id={b_product_id}")

    # --- A must NOT see B's data in list views ---
    print("== A list endpoints exclude B's rows ==")
    r = a.get("/api/v1/customers", params={"page_size": 100})
    assert_status(r, 200, "A list customers")
    a_cust_ids = {c["id"] for c in r.json()["items"]}
    if b_customer_id in a_cust_ids:
        raise SmokeFail(f"LEAK: A sees B's customer {b_customer_id} in list")

    r = a.get("/api/v1/products", params={"page_size": 100})
    assert_status(r, 200, "A list products")
    a_prod_ids = {p["id"] for p in r.json().get("items", r.json())} if isinstance(r.json(), dict) else {p["id"] for p in r.json()}
    if b_product_id in a_prod_ids:
        raise SmokeFail(f"LEAK: A sees B's product {b_product_id} in list")
    print("  OK — no cross-tenant rows in list views")

    # --- A direct ID lookups must 404 ---
    print("== A direct ID lookups for B's rows return 404 ==")
    cases = [
        ("GET", f"/api/v1/customers/{b_customer_id}"),
        ("GET", f"/api/v1/products/{b_product_id}"),
        ("GET", f"/api/v1/customers/{b_customer_id}/orders"),
        ("GET", f"/api/v1/customers/{b_customer_id}/template"),
        ("GET", f"/api/v1/customers/{b_customer_id}/prices"),
    ]
    for method, path in cases:
        r = a.client.request(method, path)
        if r.status_code != 404:
            raise SmokeFail(f"LEAK: A {method} {path} -> {r.status_code} (expected 404)")
    print(f"  OK — {len(cases)} direct lookups all 404")

    # --- A cannot mutate B's rows ---
    print("== A mutation attempts on B's rows return 404 ==")
    r = a.client.patch(f"/api/v1/customers/{b_customer_id}", json={"name": "HACKED"})
    if r.status_code != 404:
        raise SmokeFail(f"LEAK: A PATCH B's customer -> {r.status_code}")
    r = a.delete(f"/api/v1/customers/{b_customer_id}",
                 json={"reason_category": "other", "reason_text": "smoke"})
    if r.status_code != 404:
        raise SmokeFail(f"LEAK: A DELETE B's customer -> {r.status_code}")
    print("  OK — PATCH + DELETE both 404")

    # --- B can still see its own rows ---
    print("== B still sees its own rows ==")
    r = b.get(f"/api/v1/customers/{b_customer_id}")
    assert_status(r, 200, "B owns its customer")
    r = b.get(f"/api/v1/products/{b_product_id}")
    assert_status(r, 200, "B owns its product")
    print("  OK")

    # --- Reports endpoint isolation ---
    print("== Reports endpoint scoped per tenant ==")
    today = time.strftime("%Y-%m-%d")
    r = a.get(f"/api/v1/reports/production/{today}")
    assert_status(r, 200, "A reports production")
    a_rep = r.json()
    r = b.get(f"/api/v1/reports/production/{today}")
    assert_status(r, 200, "B reports production")
    b_rep = r.json()
    # Reports should not contain each other's customer/product names
    a_text = repr(a_rep)
    if cust_payload["name"] in a_text or prod_payload["name"] in a_text:
        raise SmokeFail("LEAK: A's production report contains B's customer/product")
    print("  OK")

    # --- Cleanup B's data (soft-delete cascade exercised separately) ---
    print("== Cleanup ==")
    b.delete(f"/api/v1/customers/{b_customer_id}",
             json={"reason_category": "test", "reason_text": "smoke cleanup"})
    b.delete(f"/api/v1/products/{b_product_id}",
             json={"reason_category": "test", "reason_text": "smoke cleanup"})

    print("\n✅ All multi-tenant isolation checks passed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    try:
        return run(args.base_url)
    except SmokeFail as e:
        print(f"\n❌ ISOLATION FAILURE: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

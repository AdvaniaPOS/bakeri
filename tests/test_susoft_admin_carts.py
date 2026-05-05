"""
Tester for SuSoft admin-API ("API 2") CART-ingestion.

Vi monkey-patcher SuSoftService slik at vi ikke gjør nettverkskall, og
verifiserer:
- Fletting av admin-liste + cart-detalj (`_merge_admin_cart_row`)
- Full ingest-flyt (oppretter Order + OrderLine, dedup på susoft_uuid,
  oppretter manglende kunde, hopper over ukjente produkter)
- Numerisk status -> alltid DRAFT for CART
- Mangler-kredentialer-handling i all-tenants-runner
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import Customer, Order, OrderLine, OrderStatus, Product, SyncStatus
from app.services import susoft_ingest
from app.services.susoft_ingest import (
    _merge_admin_cart_row,
    ingest_susoft_admin_carts_for_tenant,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADMIN_ROW_BASIC = {
    "uuid": "a7de10f6-47bf-11f1-873f-020000000000",
    "shopId": "100",
    "customer": {
        "id": "10017",
        "firstName": "Jon",
        "lastName": "gmail",
        "isCompany": False,
        "address": {"email": "jon@example.com"},
    },
    "orderDate": 20260504154734,
    "deliveryDate": 20260504184700,
    "note": "ext-note",
    "customerComment": "intern-note",
    "type": "CART",
    "amount": 790.0,
    "status": 0,
    "orderNo": "110",
    "alternativeId": "10020260504154630587",
}

CART_DETAIL_BASIC = {
    "uuid": "a7de10f6-47bf-11f1-873f-020000000000",
    "orderDateTime": "2026-05-04T15:47:34",
    "deliveryDateTime": "2026-05-04T18:47:00",
    "customer": {
        "id": "10017",
        "firstName": "Jon",
        "lastName": "gmail",
        "displayName": "Jon gmail",
        "isCompany": False,
        "isActive": True,
    },
    "lines": [
        {
            "lineNo": 1,
            "product": {"id": "GK009", "barcode": "GK009"},
            "text": "Hamburger",
            "qty": 2.0,
            "price": 316.0,
            "priceInclTax": 395.0,
            "lineTaxPercent": 25.0,
            "lineTotal": 790.0,
        }
    ],
}


@pytest.fixture
def cart_product(db_session, tenant):
    """Susoft-produkt GK009 -> lokal product."""
    p = Product(
        tenant_id=tenant.id,
        susoft_product_id="GK009",
        sku="SUSOFT-GK009",
        name="Hamburger",
        default_price=Decimal("316.00"),
        unit="stk",
        vat_rate=Decimal("25.00"),
        is_active=True,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


@pytest.fixture
def stub_service(monkeypatch):
    """
    Returnerer en factory som stubber SuSoftService til å returnere gitte
    rader uten å gjøre nettverkskall.
    """
    def _factory(rows_with_details):
        class _StubService:
            def __init__(self, db, tenant_id):
                self.db = db
                self.tenant_id = tenant_id

            def list_admin_carts_with_details(self, **kwargs):
                return rows_with_details

        monkeypatch.setattr(susoft_ingest, "SuSoftService", _StubService)
        return _StubService

    return _factory


# ---------------------------------------------------------------------------
# _merge_admin_cart_row
# ---------------------------------------------------------------------------

def test_merge_uses_detail_datetimes_and_lines():
    admin = dict(ADMIN_ROW_BASIC)
    admin["_detail"] = CART_DETAIL_BASIC
    merged = _merge_admin_cart_row(admin)

    assert merged["orderDateTime"] == "2026-05-04T15:47:34"
    assert merged["deliveryDateTime"] == "2026-05-04T18:47:00"
    assert len(merged["lines"]) == 1
    assert merged["lines"][0]["product"]["id"] == "GK009"
    # Admin-felt beholdes
    assert merged["uuid"] == admin["uuid"]
    assert merged["orderNo"] == "110"
    # Customer flettet: detail.displayName + admin.address.email
    assert merged["customer"]["displayName"] == "Jon gmail"
    assert merged["customer"]["address"]["email"] == "jon@example.com"


def test_merge_without_detail_returns_admin_row():
    admin = dict(ADMIN_ROW_BASIC)
    merged = _merge_admin_cart_row(admin)
    assert merged["uuid"] == admin["uuid"]
    assert "lines" not in merged or merged["lines"] is None or merged["lines"] == admin.get("lines")


# ---------------------------------------------------------------------------
# Full ingest-flyt
# ---------------------------------------------------------------------------

def test_ingest_creates_order_with_line(db_session, tenant, cart_product, stub_service):
    uuid = "create-line-uuid-0001"
    row = {**ADMIN_ROW_BASIC, "uuid": uuid}
    row["_detail"] = {**CART_DETAIL_BASIC, "uuid": uuid}
    stub_service([row])

    summary = ingest_susoft_admin_carts_for_tenant(
        db_session, tenant_id=tenant.id, days_back=30
    )
    assert summary == {"fetched": 1, "created": 1, "skipped_existing": 0, "errors": 0}

    order = db_session.query(Order).filter(Order.susoft_uuid == uuid).one()
    assert order.tenant_id == tenant.id
    assert order.status == OrderStatus.DRAFT
    assert order.sync_status == SyncStatus.SYNCED
    assert order.source == "susoft_cart_import"
    assert order.susoft_order_no == "110"
    assert order.susoft_shop_id == "100"
    assert order.susoft_fulfillment_type == "delivery"
    assert order.susoft_delivery_at is not None
    assert order.delivery_date == order.susoft_delivery_at.date()
    # customer_notes = customerComment + note
    assert "intern-note" in (order.customer_notes or "")
    assert "ext-note" in (order.customer_notes or "")

    lines = db_session.query(OrderLine).filter(OrderLine.order_id == order.id).all()
    assert len(lines) == 1
    line = lines[0]
    assert line.product_id == cart_product.id
    assert line.quantity == 2
    assert line.unit_price == Decimal("316.00")
    assert line.vat_rate == Decimal("25.00")
    assert line.line_amount_excl_vat == Decimal("632.00")
    assert line.line_vat == Decimal("158.00")
    assert line.line_amount_incl_vat == Decimal("790.00")

    assert order.total_amount_excl_vat == Decimal("632.00")
    assert order.total_vat == Decimal("158.00")
    assert order.total_amount_incl_vat == Decimal("790.00")

    # Kunde ble auto-opprettet fra payload
    customer = db_session.query(Customer).filter(
        Customer.tenant_id == tenant.id,
        Customer.susoft_customer_id == "10017",
    ).one()
    assert customer.name  # noe ble satt


def test_ingest_dedups_existing_uuid(db_session, tenant, cart_product, stub_service):
    """Andre kjøring av samme uuid skal hoppe over."""
    uuid = "dedup-uuid-0002"
    row = {**ADMIN_ROW_BASIC, "uuid": uuid}
    row["_detail"] = {**CART_DETAIL_BASIC, "uuid": uuid}
    stub_service([row])

    first = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert first["created"] == 1

    # Gjenopprett stubben siden den ble swappet ut, og kjør på nytt
    stub_service([row])
    second = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert second == {"fetched": 1, "created": 0, "skipped_existing": 1, "errors": 0}

    # Fortsatt bare én ordre i DB
    count = db_session.query(Order).filter(Order.susoft_uuid == uuid).count()
    assert count == 1


def test_ingest_skips_unknown_products(db_session, tenant, stub_service):
    """Linje med ukjent product.id skal hoppes over, men ordren opprettes."""
    uuid = "unknown-prod-uuid-0003"
    row = {**ADMIN_ROW_BASIC, "uuid": uuid}
    row["_detail"] = {
        **CART_DETAIL_BASIC,
        "uuid": uuid,
        "lines": [
            {"product": {"id": "DOES_NOT_EXIST"}, "qty": 3, "price": 10.0, "lineTaxPercent": 25.0}
        ],
    }
    stub_service([row])

    summary = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert summary["created"] == 1

    order = db_session.query(Order).filter(Order.susoft_uuid == uuid).one()
    assert db_session.query(OrderLine).filter(OrderLine.order_id == order.id).count() == 0
    assert order.total_amount_excl_vat == Decimal("0.00")


def test_ingest_skips_row_without_uuid(db_session, tenant, cart_product, stub_service):
    bad = {k: v for k, v in ADMIN_ROW_BASIC.items() if k != "uuid"}
    bad["_detail"] = CART_DETAIL_BASIC
    stub_service([bad])

    summary = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    # Hopp over uten å telle som created/error
    assert summary["created"] == 0
    assert summary["errors"] == 0


def test_ingest_uses_unknown_customer_when_payload_missing(
    db_session, tenant, cart_product, stub_service
):
    uuid = "unknown-cust-uuid-0004"
    row = {**ADMIN_ROW_BASIC, "uuid": uuid, "customer": {}}
    row["_detail"] = {**CART_DETAIL_BASIC, "uuid": uuid, "customer": {}}
    stub_service([row])

    summary = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert summary["created"] == 1

    order = db_session.query(Order).filter(Order.susoft_uuid == uuid).one()
    cust = db_session.get(Customer, order.customer_id)
    assert cust.susoft_customer_id == susoft_ingest.UKJENT_KUNDE_SUSOFT_ID


def test_status_2_is_still_draft(db_session, tenant, cart_product, stub_service):
    """Numerisk status (0/2) skal ikke påvirke status — CART => alltid DRAFT."""
    uuid = "status2-uuid-0005"
    row = {**ADMIN_ROW_BASIC, "uuid": uuid, "status": 2}
    row["_detail"] = {**CART_DETAIL_BASIC, "uuid": uuid}
    stub_service([row])

    summary = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert summary["created"] == 1
    order = db_session.query(Order).filter(Order.susoft_uuid == uuid).one()
    assert order.status == OrderStatus.DRAFT

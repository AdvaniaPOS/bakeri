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
    assert summary == {
        "fetched": 1, "created": 1, "updated": 0,
        "skipped_existing": 0, "skipped_pending_push": 0,
        "skipped_non_draft": 0, "errors": 0,
    }

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
    # SuSoft `price`=316 er INKL. mva (25%) -> lokal unit_price = 316/1.25 = 252.80 ekskl.
    assert line.unit_price == Decimal("252.8000")
    assert line.vat_rate == Decimal("25.00")
    assert line.line_amount_excl_vat == Decimal("505.60")
    assert line.line_vat == Decimal("126.40")
    assert line.line_amount_incl_vat == Decimal("632.00")

    assert order.total_amount_excl_vat == Decimal("505.60")
    assert order.total_vat == Decimal("126.40")
    assert order.total_amount_incl_vat == Decimal("632.00")

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
    assert second == {
        "fetched": 1, "created": 0, "updated": 0,
        "skipped_existing": 1, "skipped_pending_push": 0,
        "skipped_non_draft": 0, "errors": 0,
    }

    # Fortsatt bare én ordre i DB
    count = db_session.query(Order).filter(Order.susoft_uuid == uuid).count()
    assert count == 1


def test_ingest_updates_existing_when_susoft_changed(
    db_session, tenant, cart_product, stub_service
):
    """
    Pull-side av to-veis sync: hvis SuSoft har endret carten siden forrige
    pull (qty/dato/notater), skal lokal DRAFT oppdateres tilsvarende.
    """
    uuid = "pull-update-uuid-0006"
    # Første pull: qty=2
    row1 = {**ADMIN_ROW_BASIC, "uuid": uuid}
    row1["_detail"] = {**CART_DETAIL_BASIC, "uuid": uuid}
    stub_service([row1])

    s1 = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert s1["created"] == 1
    order = db_session.query(Order).filter(Order.susoft_uuid == uuid).one()
    first_hash = order.susoft_payload_hash
    assert first_hash is not None

    # Ny pull, ingen endring -> skipped_existing
    stub_service([row1])
    s2 = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert s2["updated"] == 0
    assert s2["skipped_existing"] == 1

    # SuSoft endrer qty 2 -> 5 og kommentar
    row2 = {**ADMIN_ROW_BASIC, "uuid": uuid, "customerComment": "endret kommentar"}
    detail2 = {**CART_DETAIL_BASIC, "uuid": uuid}
    detail2_lines = []
    for ln in detail2["lines"]:
        new_ln = dict(ln)
        new_ln["qty"] = 5
        new_ln["qtyOrdered"] = 5
        detail2_lines.append(new_ln)
    detail2["lines"] = detail2_lines
    row2["_detail"] = detail2
    stub_service([row2])

    s3 = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert s3["updated"] == 1
    assert s3["created"] == 0
    assert s3["skipped_existing"] == 0

    db_session.refresh(order)
    assert order.susoft_payload_hash != first_hash
    assert "endret kommentar" in (order.customer_notes or "")
    lines = db_session.query(OrderLine).filter(OrderLine.order_id == order.id).all()
    assert len(lines) == 1
    assert lines[0].quantity == 5
    # 5 * 252.80 = 1264.00 ekskl. mva
    assert order.total_amount_excl_vat == Decimal("1264.00")


def test_ingest_skips_update_when_pending_push(
    db_session, tenant, cart_product, stub_service
):
    """
    Hvis lokal har susoft_pending_push=True, skal pull IKKE overskrive
    (push vinner — venter på at lokal endring blir pushet til SuSoft).
    """
    uuid = "pending-push-uuid-0007"
    row = {**ADMIN_ROW_BASIC, "uuid": uuid}
    row["_detail"] = {**CART_DETAIL_BASIC, "uuid": uuid}
    stub_service([row])
    ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)

    order = db_session.query(Order).filter(Order.susoft_uuid == uuid).one()
    order.susoft_pending_push = True
    db_session.commit()

    # SuSoft har endret qty
    row2 = {**ADMIN_ROW_BASIC, "uuid": uuid}
    detail2 = {**CART_DETAIL_BASIC, "uuid": uuid}
    detail2["lines"] = [{**ln, "qty": 99, "qtyOrdered": 99} for ln in detail2["lines"]]
    row2["_detail"] = detail2
    stub_service([row2])

    s = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert s["skipped_pending_push"] == 1
    assert s["updated"] == 0

    # Lokal qty fortsatt 2 (ikke 99)
    lines = db_session.query(OrderLine).filter(OrderLine.order_id == order.id).all()
    assert len(lines) == 1
    assert lines[0].quantity == 2


def test_ingest_skips_update_when_status_not_draft(
    db_session, tenant, cart_product, stub_service
):
    """Hvis lokal status ikke lenger er DRAFT, skal pull la ordren være."""
    uuid = "non-draft-uuid-0008"
    row = {**ADMIN_ROW_BASIC, "uuid": uuid}
    row["_detail"] = {**CART_DETAIL_BASIC, "uuid": uuid}
    stub_service([row])
    ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)

    order = db_session.query(Order).filter(Order.susoft_uuid == uuid).one()
    order.status = OrderStatus.CONFIRMED
    db_session.commit()

    # SuSoft endrer
    row2 = {**ADMIN_ROW_BASIC, "uuid": uuid, "customerComment": "vil bli ignorert"}
    detail2 = {**CART_DETAIL_BASIC, "uuid": uuid}
    detail2["lines"] = [{**ln, "qty": 99, "qtyOrdered": 99} for ln in detail2["lines"]]
    row2["_detail"] = detail2
    stub_service([row2])

    s = ingest_susoft_admin_carts_for_tenant(db_session, tenant_id=tenant.id)
    assert s["skipped_non_draft"] == 1
    assert s["updated"] == 0

    db_session.refresh(order)
    assert "vil bli ignorert" not in (order.customer_notes or "")


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

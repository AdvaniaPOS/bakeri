"""
Unit-test for SuSoft produkt-sync med fokus på aktiv/skjult-logikken.

Vi monkey-patcher de eksterne HTTP-kallene slik at vi kan verifisere at:
- Et produkt som kommer fra Susoft med active=False blir lagret som skjult
- Hvis en admin har overstyrt et aktivt produkt til skjult, så blir overstyringen
  respektert så lenge Susoft fortsatt sier active=True
- Hvis Susoft sier active=False så nullstilles override slik at fremtidig
  re-aktivering virker
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import Product
from app.services.susoft import SuSoftService


@pytest.fixture
def susoft_service(db_session, tenant, monkeypatch):
    svc = SuSoftService(db_session, tenant_id=tenant.id)
    # Unngå nettverkskall for kategorier
    monkeypatch.setattr(svc, "_fetch_category_name_map", lambda: {})
    # Unngå _create_alert som kan kreve flere tabeller
    monkeypatch.setattr(svc, "_create_alert", lambda **kw: None)
    return svc


def _stub_products(svc, items):
    """Stub /product/search til å returnere `items` (full sync)."""
    svc._fetch_paginated_product_search = lambda page_size=200: items


def test_susoft_inactive_hides_product(db_session, tenant, susoft_service):
    # Eksisterende produkt som er aktivt i vår DB
    p = Product(
        tenant_id=tenant.id,
        susoft_product_id="P100",
        sku="SUSOFT-P100",
        name="Solbolle",
        default_price=Decimal("18.00"),
        unit="stk",
        vat_rate=Decimal("15.00"),
        is_active=True,
        is_active_overridden=False,
    )
    db_session.add(p)
    db_session.commit()

    _stub_products(susoft_service, [
        {"id": "P100", "name": "Solbolle", "retailPrice": 18.0, "active": False, "vatPercent": 15},
    ])
    result = susoft_service.sync_products_from_susoft()
    assert result["updated"] == 1

    db_session.refresh(p)
    assert p.is_active is False
    assert p.is_active_overridden is False  # nullstilt


def test_susoft_active_respects_local_override(db_session, tenant, susoft_service):
    """Admin har skjult produktet manuelt — Susoft sier aktivt — vi beholder skjult."""
    p = Product(
        tenant_id=tenant.id,
        susoft_product_id="P200",
        sku="SUSOFT-P200",
        name="Kanelbolle",
        default_price=Decimal("22.00"),
        unit="stk",
        vat_rate=Decimal("15.00"),
        is_active=False,
        is_active_overridden=True,
    )
    db_session.add(p)
    db_session.commit()

    _stub_products(susoft_service, [
        {"id": "P200", "name": "Kanelbolle", "retailPrice": 22.0, "active": True, "vatPercent": 15},
    ])
    susoft_service.sync_products_from_susoft()

    db_session.refresh(p)
    assert p.is_active is False
    assert p.is_active_overridden is True


def test_susoft_active_no_override_keeps_active(db_session, tenant, susoft_service):
    p = Product(
        tenant_id=tenant.id,
        susoft_product_id="P300",
        sku="SUSOFT-P300",
        name="Rundstykke",
        default_price=Decimal("12.00"),
        unit="stk",
        vat_rate=Decimal("15.00"),
        is_active=False,
        is_active_overridden=False,
    )
    db_session.add(p)
    db_session.commit()

    _stub_products(susoft_service, [
        {"id": "P300", "name": "Rundstykke", "retailPrice": 12.0, "active": True, "vatPercent": 15},
    ])
    susoft_service.sync_products_from_susoft()

    db_session.refresh(p)
    assert p.is_active is True


def test_susoft_creates_new_inactive_product(db_session, tenant, susoft_service):
    _stub_products(susoft_service, [
        {"id": "P400", "name": "Avregistrert kake", "retailPrice": 99.0, "active": False, "vatPercent": 15},
    ])
    result = susoft_service.sync_products_from_susoft()
    assert result["created"] == 1

    p = db_session.query(Product).filter(
        Product.tenant_id == tenant.id, Product.susoft_product_id == "P400"
    ).first()
    assert p is not None
    assert p.is_active is False


def test_susoft_sync_stores_alternative_price_and_vat(db_session, tenant, susoft_service):
    _stub_products(susoft_service, [
        {
            "id": "P500",
            "name": "Takeaway-bolle",
            "retailPrice": 30.0,
            "alternativePrice": 24.0,
            "vatPercent": 25,
            "alternativeVatPercent": 15,
            "active": True,
        },
    ])

    result = susoft_service.sync_products_from_susoft()
    assert result["created"] == 1

    p = db_session.query(Product).filter(
        Product.tenant_id == tenant.id,
        Product.susoft_product_id == "P500",
    ).first()
    assert p is not None
    assert p.default_price == Decimal("30.00")
    assert p.alternative_price == Decimal("24.00")
    assert p.vat_rate == Decimal("25.00")
    assert p.alternative_vat_rate == Decimal("15.00")

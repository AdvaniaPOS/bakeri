from datetime import date
from decimal import Decimal

from app.models import Customer, Order, OrderLine, OrderStatus, Product, SyncStatus
from app.services.susoft import SuSoftService


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "" if payload is None else str(payload)

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


def _create_order_with_line(db_session, tenant, customer):
    product = Product(
        tenant_id=tenant.id,
        sku="TEST-100",
        name="Bolle",
        default_price=Decimal("39.00"),
        unit="stk",
        vat_rate=Decimal("15.00"),
        is_active=True,
        susoft_product_id="BAKERI008",
    )
    db_session.add(product)
    db_session.flush()

    order = Order(
        tenant_id=tenant.id,
        customer_id=customer.id,
        delivery_date=date(2026, 6, 12),
        status=OrderStatus.CONFIRMED,
        sync_status=SyncStatus.PENDING,
        total_amount_excl_vat=Decimal("39.00"),
        total_vat=Decimal("5.85"),
        total_amount_incl_vat=Decimal("44.85"),
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        tenant_id=tenant.id,
        order_id=order.id,
        product_id=product.id,
        quantity=1,
        unit_price=Decimal("39.00"),
        vat_rate=Decimal("15.00"),
        line_amount_excl_vat=Decimal("39.00"),
        line_vat=Decimal("5.85"),
        line_amount_incl_vat=Decimal("44.85"),
    )
    db_session.add(line)
    db_session.commit()
    db_session.refresh(order)
    return order


def test_create_order_repairs_invalid_customer_id_using_best_local_match(
    db_session,
    tenant,
    monkeypatch,
):
    broken_customer = Customer(
        tenant_id=tenant.id,
        name="Jon Sigurdarson",
        contact_person="Jon",
        email="jon.vidar.sigurdarson@gmail.com",
        is_active=True,
        susoft_customer_id="100002",
    )
    exact_name_candidate = Customer(
        tenant_id=tenant.id,
        name="Jon Sigurdarson",
        contact_person="Jon",
        phone="48893472",
        postal_code="3414",
        city="Lierskogen",
        is_active=True,
        susoft_customer_id="10007",
    )
    email_only_candidate = Customer(
        tenant_id=tenant.id,
        name="Jon1100011 4AEC151C",
        contact_person="Jon1100011",
        email="jon.vidar.sigurdarson@gmail.com",
        phone="+4748893472",
        street_address="Tveitabakken 13",
        postal_code="3420",
        city="Lierskogen",
        is_active=True,
        susoft_customer_id="10098",
    )
    irrelevant_candidate = Customer(
        tenant_id=tenant.id,
        name="Helt Annen Kunde",
        contact_person="Annen",
        email="annen@example.com",
        is_active=True,
        susoft_customer_id="20001",
    )
    db_session.add_all([broken_customer, exact_name_candidate, email_only_candidate, irrelevant_candidate])
    db_session.commit()
    db_session.refresh(broken_customer)

    order = _create_order_with_line(db_session, tenant, broken_customer)
    service = SuSoftService(db_session, tenant_id=tenant.id)

    post_payload = {}
    looked_up_ids = []

    def fake_get_customer_by_id(customer_id):
        looked_up_ids.append(customer_id)
        if customer_id == "100002":
            return None
        if customer_id == "10007":
            return {
                "id": "10007",
                "firstName": "Jon",
                "lastName": "Sigurdarson",
                "displayName": "Jon Sigurdarson",
                "address": {"city": "Lierskogen", "zipCode": "3414", "mobilePhone": "48893472"},
            }
        if customer_id == "10098":
            return {
                "id": "10098",
                "firstName": "Jon1100011",
                "lastName": "4AEC151C",
                "displayName": "Jon1100011 4AEC151C",
                "address": {
                    "city": "Lierskogen",
                    "zipCode": "3420",
                    "addressLine1": "Tveitabakken 13",
                    "mobilePhone": "+4748893472",
                    "email": "jon.vidar.sigurdarson@gmail.com",
                },
            }
        raise AssertionError(f"Unexpected customer lookup: {customer_id}")

    def fake_post(endpoint, json, headers):
        post_payload["endpoint"] = endpoint
        post_payload["json"] = json
        return _FakeResponse(201, {"orderNo": 900001})

    def fake_order_push_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/order"
        return fake_post(path, kwargs["json"], kwargs["headers"])

    monkeypatch.setattr(service, "_fetch_order_by_alt_id", lambda alt_id, memoize_pre_post_miss=False: (None, True))
    monkeypatch.setattr(service, "get_customer_by_id", fake_get_customer_by_id)
    monkeypatch.setattr(service, "get_product_by_id", lambda product_id: {"id": product_id})
    monkeypatch.setattr(service, "_get_headers", lambda: {})
    monkeypatch.setattr(service, "_log_sync", lambda **kwargs: None)
    monkeypatch.setattr(service, "_request_with_order_push_pacing", fake_order_push_request)

    result = service.create_order(order)

    db_session.refresh(broken_customer)
    assert result == "900001"
    assert broken_customer.susoft_customer_id == "100002"
    assert post_payload["endpoint"] == "/order"
    assert post_payload["json"]["customer"]["id"] == "10007"
    assert "20001" not in looked_up_ids


def test_sync_customers_skips_duplicate_unloadable_customer_ids(
    db_session,
    tenant,
    monkeypatch,
):
    service = SuSoftService(db_session, tenant_id=tenant.id)

    monkeypatch.setattr(
        service,
        "_fetch_paginated_get",
        lambda endpoint, params=None, page_size=200: [
            {
                "id": "100002",
                "firstName": "Jon",
                "lastName": "Sigurdarson",
                "displayName": "Jon Sigurdarson",
                "address": {"email": "jon.vidar.sigurdarson@gmail.com"},
            },
            {
                "id": "100002",
                "lastName": "SpareBank 1 Buskerud-Vestfold",
                "displayName": "SpareBank 1 Buskerud-Vestfold",
                "address": {"email": "faktura@s1bv.no"},
            },
            {
                "id": "10007",
                "firstName": "Jon",
                "lastName": "Sigurdarson",
                "displayName": "Jon Sigurdarson",
                "address": {"city": "Lierskogen", "zipCode": "3414", "mobilePhone": "48893472"},
                "isActive": True,
            },
        ],
    )
    monkeypatch.setattr(
        service,
        "get_customer_by_id",
        lambda customer_id: None if customer_id == "100002" else {"id": customer_id},
    )
    monkeypatch.setattr(service, "_create_alert", lambda **kwargs: None)

    result = service.sync_customers_from_susoft()

    customers = db_session.query(Customer).filter(Customer.tenant_id == tenant.id).all()
    susoft_ids = sorted(customer.susoft_customer_id for customer in customers if customer.susoft_customer_id)
    assert result == {"created": 1, "updated": 0, "errors": 0, "fetched": 1}
    assert susoft_ids == ["10007"]
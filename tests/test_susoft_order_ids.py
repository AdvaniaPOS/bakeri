import json
from datetime import date
from decimal import Decimal

import pytest
import app.services.susoft as susoft_module

from app.models import Order, OrderLine, OrderStatus, SyncStatus
from app.services.susoft import (
    SuSoftAPIError,
    SuSoftService,
    _alternative_id_for_order,
    _clear_lookup_caches,
)
from app.services.susoft_ingest import (
    _extract_local_order_refs_from_alt_id,
    ingest_susoft_orders_for_tenant,
)


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _reset_susoft_lookup_caches():
    _clear_lookup_caches()
    yield
    _clear_lookup_caches()


def _create_order_with_line(db_session, tenant, customer, product):
    customer.susoft_customer_id = "CUST-100"
    product.susoft_product_id = "PROD-100"
    order = Order(
        tenant_id=tenant.id,
        customer_id=customer.id,
        delivery_date=date(2026, 6, 12),
        status=OrderStatus.CONFIRMED,
        sync_status=SyncStatus.PENDING,
        total_amount_excl_vat=Decimal("200.00"),
        total_vat=Decimal("30.00"),
        total_amount_incl_vat=Decimal("230.00"),
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        tenant_id=tenant.id,
        order_id=order.id,
        product_id=product.id,
        quantity=1,
        unit_price=Decimal("200.00"),
        vat_rate=Decimal("15.00"),
        line_amount_excl_vat=Decimal("200.00"),
        line_vat=Decimal("30.00"),
        line_amount_incl_vat=Decimal("230.00"),
    )
    db_session.add(line)
    db_session.commit()
    db_session.refresh(order)
    return order


def test_create_order_uses_uuid_alt_id_and_skips_raw_numeric_fallback(
    db_session,
    tenant,
    customer,
    product,
    monkeypatch,
):
    order = _create_order_with_line(db_session, tenant, customer, product)
    service = SuSoftService(db_session, tenant_id=tenant.id)

    seen_alt_ids = []
    post_payload = {}

    def fake_fetch_order_by_alt_id(alt_id, memoize_pre_post_miss=False):
        seen_alt_ids.append(alt_id)
        if alt_id == str(order.id):
            return {"orderNo": 501817}, False
        return None, True

    def fake_order_push_request(method, path, **kwargs):
        assert method == "POST"
        post_payload["endpoint"] = path
        post_payload["json"] = kwargs["json"]
        post_payload["headers"] = kwargs["headers"]
        return _FakeResponse(201, {"orderNo": 900001})

    monkeypatch.setattr(service, "_fetch_order_by_alt_id", fake_fetch_order_by_alt_id)
    monkeypatch.setattr(service, "get_customer_by_id", lambda customer_id: {"id": customer_id})
    monkeypatch.setattr(service, "get_product_by_id", lambda product_id: {"id": product_id})
    monkeypatch.setattr(service, "_get_headers", lambda: {})
    monkeypatch.setattr(service, "_log_sync", lambda **kwargs: None)
    monkeypatch.setattr(service, "_request_with_order_push_pacing", fake_order_push_request)

    result = service.create_order(order)

    assert result == "900001"
    assert str(order.id) not in seen_alt_ids
    assert post_payload["endpoint"] == "/order"
    assert post_payload["json"]["alternativeId"] == _alternative_id_for_order(order)
    assert order.order_uuid.hex in post_payload["json"]["alternativeId"]


def test_lookup_cache_reuses_recent_customer_product_and_order_hits_across_service_instances(
    db_session,
    tenant,
    monkeypatch,
):
    monkeypatch.setattr(susoft_module, "ORDER_PUSH_REQUEST_PACING_SECONDS", 0.0)

    service_one = SuSoftService(db_session, tenant_id=tenant.id)
    service_two = SuSoftService(db_session, tenant_id=tenant.id)

    request_counts = {"customer": 0, "product": 0, "order": 0}
    alt_id = "t1-oucachehit"

    def fake_request(method, path, **kwargs):
        assert method == "GET"
        if path == "/customer/id?id=10098":
            request_counts["customer"] += 1
            return _FakeResponse(200, {"id": "10098", "displayName": "Jon1100011 4AEC151C"})
        if path == "/product/id?productId=KULI010":
            request_counts["product"] += 1
            return _FakeResponse(200, {"id": "KULI010", "name": "Kuli"})
        if path == f"/order/altid?altId={alt_id}":
            request_counts["order"] += 1
            return _FakeResponse(200, {"orderNo": 501819, "alternativeId": alt_id})
        raise AssertionError(f"Unexpected request path: {path}")

    for service in (service_one, service_two):
        monkeypatch.setattr(service, "_get_headers", lambda: {})
        monkeypatch.setattr(service.client, "request", fake_request)

    assert service_one.get_customer_by_id("10098")["id"] == "10098"
    assert service_one.get_product_by_id("KULI010")["id"] == "KULI010"
    assert service_one.get_order_by_alt_id(alt_id)["orderNo"] == 501819
    assert service_two.get_customer_by_id("10098")["id"] == "10098"
    assert service_two.get_product_by_id("KULI010")["id"] == "KULI010"
    assert service_two.get_order_by_alt_id(alt_id)["orderNo"] == 501819
    assert request_counts == {"customer": 1, "product": 1, "order": 1}


def test_create_order_reuses_missing_alt_id_checks_until_first_post_attempt(
    db_session,
    tenant,
    customer,
    product,
    monkeypatch,
):
    order = _create_order_with_line(db_session, tenant, customer, product)
    service = SuSoftService(db_session, tenant_id=tenant.id)

    alt_id_requests = []
    post_calls = []
    product_attempts = {"count": 0}

    def fake_order_push_request(method, path, **kwargs):
        if method == "GET" and path.startswith("/order/altid?altId="):
            alt_id_requests.append(path)
            return _FakeResponse(404, None)
        if method == "POST" and path == "/order":
            post_calls.append(path)
            return _FakeResponse(201, {"orderNo": 900001})
        raise AssertionError(f"Unexpected request: {method} {path}")

    def fake_get_product_by_id(product_id):
        if product_attempts["count"] == 0:
            product_attempts["count"] += 1
            raise SuSoftAPIError("Failed to fetch SuSoft product PROD-100: 429", 429)
        return {"id": product_id}

    monkeypatch.setattr(service, "_request_with_order_push_pacing", fake_order_push_request)
    monkeypatch.setattr(service, "get_customer_by_id", lambda customer_id: {"id": customer_id})
    monkeypatch.setattr(service, "get_product_by_id", fake_get_product_by_id)
    monkeypatch.setattr(service, "_get_headers", lambda: {})
    monkeypatch.setattr(service, "_log_sync", lambda **kwargs: None)

    with pytest.raises(SuSoftAPIError, match="PROD-100: 429"):
        SuSoftService.create_order.__wrapped__(service, order)

    result = SuSoftService.create_order.__wrapped__(service, order)

    assert result == "900001"
    assert len(alt_id_requests) == 2
    assert post_calls == ["/order"]


def test_order_push_requests_are_paced_across_service_instances(
    db_session,
    tenant,
    monkeypatch,
):
    monkeypatch.setattr(susoft_module, "ORDER_PUSH_REQUEST_PACING_SECONDS", 0.5)

    clock = {"now": 100.0}
    sleep_calls = []
    request_times = []

    def fake_monotonic():
        return clock["now"]

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        clock["now"] += seconds

    def fake_request(method, path, **kwargs):
        request_times.append((method, path, clock["now"]))
        return _FakeResponse(200, {"id": path})

    monkeypatch.setattr(susoft_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(susoft_module.time, "sleep", fake_sleep)

    service_one = SuSoftService(db_session, tenant_id=tenant.id)
    service_two = SuSoftService(db_session, tenant_id=tenant.id)

    for service in (service_one, service_two):
        monkeypatch.setattr(service, "_get_headers", lambda: {})
        monkeypatch.setattr(service.client, "request", fake_request)

    assert service_one.get_product_by_id("P-1")["id"] == "/product/id?productId=P-1"
    assert service_two.get_customer_by_id("C-1")["id"] == "/customer/id?id=C-1"
    assert sleep_calls == [0.5]
    assert request_times[0] == ("GET", "/product/id?productId=P-1", 100.0)
    assert request_times[1] == ("GET", "/customer/id?id=C-1", 100.5)


def test_extract_local_order_refs_parses_uuid_alt_id_and_ignores_raw_numeric(
    db_session,
    tenant,
    customer,
    product,
):
    order = _create_order_with_line(db_session, tenant, customer, product)

    parsed_uuid, parsed_order_id = _extract_local_order_refs_from_alt_id(
        _alternative_id_for_order(order),
        tenant.id,
    )
    assert parsed_uuid == order.order_uuid
    assert parsed_order_id is None

    parsed_uuid, parsed_order_id = _extract_local_order_refs_from_alt_id(str(order.id), tenant.id)
    assert parsed_uuid is None
    assert parsed_order_id is None


def test_ingest_links_existing_order_by_uuid_alternative_id(
    db_session,
    tenant,
    customer,
    product,
    monkeypatch,
):
    order = _create_order_with_line(db_session, tenant, customer, product)

    def fake_list_orders(self, date_from, date_to, shop_id=None, mode="FULL"):
        return [
            {
                "uuid": "remote-uuid-1",
                "orderNo": "501817",
                "alternativeId": _alternative_id_for_order(order),
            }
        ]

    monkeypatch.setattr(SuSoftService, "list_orders", fake_list_orders)

    summary = ingest_susoft_orders_for_tenant(db_session, tenant.id, days_back=1)
    db_session.refresh(order)

    assert summary == {"fetched": 1, "created": 0, "skipped_existing": 1, "errors": 0}
    assert order.susoft_uuid == "remote-uuid-1"
    assert order.susoft_order_id == "501817"
    assert order.susoft_order_no == "501817"


def test_create_order_fails_fast_for_unloadable_customer_id(
    db_session,
    tenant,
    customer,
    product,
    monkeypatch,
):
    order = _create_order_with_line(db_session, tenant, customer, product)
    service = SuSoftService(db_session, tenant_id=tenant.id)

    request_calls = []

    monkeypatch.setattr(service, "_fetch_order_by_alt_id", lambda alt_id, memoize_pre_post_miss=False: (None, True))
    monkeypatch.setattr(service, "get_customer_by_id", lambda customer_id: None)
    monkeypatch.setattr(
        service,
        "_request_with_order_push_pacing",
        lambda method, path, **kwargs: request_calls.append((method, path, kwargs)),
    )

    with pytest.raises(SuSoftAPIError, match="SuSoft-kunde CUST-100 kan ikke lastes via /customer/id"):
        service.create_order(order)

    assert request_calls == []


def test_create_order_does_not_retry_deterministic_404_from_post(
    db_session,
    tenant,
    customer,
    product,
    monkeypatch,
):
    order = _create_order_with_line(db_session, tenant, customer, product)
    service = SuSoftService(db_session, tenant_id=tenant.id)

    post_calls = []

    monkeypatch.setattr(service, "_fetch_order_by_alt_id", lambda alt_id, memoize_pre_post_miss=False: (None, True))
    monkeypatch.setattr(service, "get_customer_by_id", lambda customer_id: {"id": customer_id})
    monkeypatch.setattr(service, "get_product_by_id", lambda product_id: {"id": product_id})
    monkeypatch.setattr(service, "_get_headers", lambda: {})
    monkeypatch.setattr(service, "_log_sync", lambda **kwargs: None)

    def fake_order_push_request(method, path, **kwargs):
        post_calls.append((method, path))
        return _FakeResponse(404, {"message": "Not Found", "code": 0})

    monkeypatch.setattr(service, "_request_with_order_push_pacing", fake_order_push_request)

    with pytest.raises(SuSoftAPIError, match="SuSoft avviste ordreoppretting med 404"):
        service.create_order(order)

    assert post_calls == [("POST", "/order")]
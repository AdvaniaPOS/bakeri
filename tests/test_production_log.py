"""
Tests for produksjonslogg-endepunktene.

Vi kaller endpoint-funksjonene direkte (ikke via TestClient) for å
unngå auth-middleware. Tenant og user injectes som argumenter.
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest


@pytest.fixture
def user(db_session, tenant):
    import os
    from app.auth_models import User, UserRole
    u = User(
        tenant_id=tenant.id,
        email=f"baker-{os.urandom(4).hex()}@test.no",
        password_hash="x",
        first_name="Bake",
        last_name="Ren",
        role=UserRole.MANAGER,
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def order_with_lines(db_session, tenant, customer, product):
    """Aktiv ordre med 10 stk på 2026-05-05."""
    from app.models import Order, OrderLine, OrderStatus, SyncStatus
    o = Order(
        tenant_id=tenant.id,
        customer_id=customer.id,
        delivery_date=date(2026, 5, 5),
        status=OrderStatus.CONFIRMED,
        sync_status=SyncStatus.PENDING,
        total_amount_excl_vat=Decimal("0"),
        total_vat=Decimal("0"),
        total_amount_incl_vat=Decimal("0"),
    )
    db_session.add(o)
    db_session.flush()
    line = OrderLine(
        tenant_id=tenant.id,
        order_id=o.id,
        product_id=product.id,
        quantity=10,
        unit_price=Decimal("12.00"),
        vat_rate=Decimal("15.00"),
        line_amount_excl_vat=Decimal("120.00"),
        line_vat=Decimal("18.00"),
        line_amount_incl_vat=Decimal("138.00"),
    )
    db_session.add(line)
    db_session.commit()
    return o


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_get_day_returns_planned_from_orders(db_session, tenant, product, order_with_lines):
    from app.api.production import get_day
    resp = _run(get_day(date(2026, 5, 5), tenant=tenant, db=db_session))
    assert resp.total_planned == 10
    assert resp.total_actual == 0
    assert len(resp.rows) == 1
    row = resp.rows[0]
    assert row.product_id == product.id
    assert row.planned_qty == 10
    assert row.log_id is None  # ingen logg ennå


def test_get_day_empty_when_no_orders(db_session, tenant):
    from app.api.production import get_day
    resp = _run(get_day(date(2030, 1, 1), tenant=tenant, db=db_session))
    assert resp.rows == []
    assert resp.total_planned == 0


def test_upsert_creates_log_and_snapshots_planned(
    db_session, tenant, user, product, order_with_lines
):
    from app.api.production import (
        get_day, upsert_day,
        ProductionDayUpsertRequest, ProductionLogUpsert,
    )
    payload = ProductionDayUpsertRequest(rows=[
        ProductionLogUpsert(
            product_id=product.id,
            actual_qty=12,
            waste_returned=1,
            waste_burnt=1,
            waste_quality=0,
            waste_other=0,
            notes="ok",
        )
    ])
    resp = _run(upsert_day(date(2026, 5, 5), payload, tenant=tenant, user=user, db=db_session))
    assert resp.total_actual == 12
    assert resp.total_waste == 2
    assert resp.total_sold == 10
    row = resp.rows[0]
    assert row.actual_qty == 12
    assert row.waste_pct == round(2 / 12 * 100, 1)
    assert row.notes == "ok"
    assert row.log_id is not None

    # Snapshot av planlagt skal være lagret
    from app.models import ProductionLog
    log = db_session.query(ProductionLog).filter_by(id=row.log_id).one()
    assert log.planned_qty == 10
    assert log.logged_by_user_id == user.id


def test_upsert_updates_existing_row(db_session, tenant, user, product, order_with_lines):
    from app.api.production import (
        upsert_day, ProductionDayUpsertRequest, ProductionLogUpsert,
    )
    first = ProductionDayUpsertRequest(rows=[
        ProductionLogUpsert(product_id=product.id, actual_qty=10, waste_returned=2)
    ])
    _run(upsert_day(date(2026, 5, 5), first, tenant=tenant, user=user, db=db_session))

    second = ProductionDayUpsertRequest(rows=[
        ProductionLogUpsert(product_id=product.id, actual_qty=15, waste_returned=0, waste_burnt=3)
    ])
    resp = _run(upsert_day(date(2026, 5, 5), second, tenant=tenant, user=user, db=db_session))

    from app.models import ProductionLog
    rows = db_session.query(ProductionLog).filter_by(
        tenant_id=tenant.id, log_date=date(2026, 5, 5), product_id=product.id
    ).all()
    assert len(rows) == 1, "Skal være kun én rad pr (tenant, date, product)"
    assert rows[0].actual_qty == 15
    assert rows[0].waste_returned == 0
    assert rows[0].waste_burnt == 3
    assert resp.rows[0].total_waste == 3


def test_upsert_unknown_product_raises_404(db_session, tenant, user):
    from fastapi import HTTPException
    from app.api.production import (
        upsert_day, ProductionDayUpsertRequest, ProductionLogUpsert,
    )
    payload = ProductionDayUpsertRequest(rows=[
        ProductionLogUpsert(product_id=999999, actual_qty=1)
    ])
    with pytest.raises(HTTPException) as exc:
        _run(upsert_day(date(2026, 5, 5), payload, tenant=tenant, user=user, db=db_session))
    assert exc.value.status_code == 404


def test_range_summary_aggregates(db_session, tenant, user, product, order_with_lines):
    from app.api.production import (
        upsert_day, range_summary,
        ProductionDayUpsertRequest, ProductionLogUpsert,
    )
    # Dag 1
    _run(upsert_day(
        date(2026, 5, 5),
        ProductionDayUpsertRequest(rows=[
            ProductionLogUpsert(product_id=product.id, actual_qty=10, waste_burnt=2)
        ]),
        tenant=tenant, user=user, db=db_session,
    ))
    # Dag 2 (uten ordre, ad-hoc baking)
    _run(upsert_day(
        date(2026, 5, 6),
        ProductionDayUpsertRequest(rows=[
            ProductionLogUpsert(product_id=product.id, actual_qty=20, waste_quality=3)
        ]),
        tenant=tenant, user=user, db=db_session,
    ))

    resp = _run(range_summary(
        from_date=date(2026, 5, 1), to_date=date(2026, 5, 10),
        tenant=tenant, db=db_session,
    ))
    assert len(resp.rows) == 1
    r = resp.rows[0]
    assert r.total_actual == 30
    assert r.total_waste == 5
    assert r.waste_pct == round(5 / 30 * 100, 1)


def test_range_summary_rejects_bad_range(db_session, tenant):
    from fastapi import HTTPException
    from app.api.production import range_summary
    with pytest.raises(HTTPException) as exc:
        _run(range_summary(
            from_date=date(2026, 5, 10), to_date=date(2026, 5, 1),
            tenant=tenant, db=db_session,
        ))
    assert exc.value.status_code == 400

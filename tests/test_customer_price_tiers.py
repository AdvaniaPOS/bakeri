from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from app.api.pricing import get_effective_pricing, propagate_customer_price_tier_change
from app.models import (
    CustomerPriceTier,
    CustomerProductPrice,
    Order,
    OrderLine,
    OrderStatus,
    SyncStatus,
)


def test_get_effective_pricing_uses_customer_price_tier_vat_and_price(
    db_session,
    tenant,
    customer,
    product,
):
    customer.susoft_price_tier = CustomerPriceTier.PRICE_2
    product.default_price = Decimal("30.00")
    product.vat_rate = Decimal("25.00")
    product.alternative_price = Decimal("24.00")
    product.alternative_vat_rate = Decimal("15.00")
    db_session.commit()

    price, vat_rate, is_specific, price_entry_id = get_effective_pricing(
        db_session,
        customer.id,
        product.id,
        date(2026, 1, 15),
        tenant_id=tenant.id,
        customer=customer,
        product=product,
    )

    assert price == Decimal("24.00")
    assert vat_rate == Decimal("15.00")
    assert is_specific is False
    assert price_entry_id is None


def test_get_effective_pricing_keeps_customer_override_price_but_uses_selected_vat(
    db_session,
    tenant,
    customer,
    product,
):
    customer.susoft_price_tier = CustomerPriceTier.PRICE_2
    product.default_price = Decimal("30.00")
    product.vat_rate = Decimal("25.00")
    product.alternative_price = Decimal("24.00")
    product.alternative_vat_rate = Decimal("15.00")
    db_session.add(
        CustomerProductPrice(
            tenant_id=tenant.id,
            customer_id=customer.id,
            product_id=product.id,
            price=Decimal("21.50"),
            effective_from_date=date(2026, 1, 1),
        )
    )
    db_session.commit()

    price, vat_rate, is_specific, price_entry_id = get_effective_pricing(
        db_session,
        customer.id,
        product.id,
        date(2026, 1, 15),
        tenant_id=tenant.id,
        customer=customer,
        product=product,
    )

    assert price == Decimal("21.50")
    assert vat_rate == Decimal("15.00")
    assert is_specific is True
    assert price_entry_id is not None


def test_propagate_customer_price_tier_change_reprices_existing_unlocked_orders(
    db_session,
    tenant,
    customer,
    product,
):
    delivery_date = date(2026, 1, 15)
    product.default_price = Decimal("30.00")
    product.vat_rate = Decimal("25.00")
    product.alternative_price = Decimal("24.00")
    product.alternative_vat_rate = Decimal("15.00")

    order = Order(
        tenant_id=tenant.id,
        customer_id=customer.id,
        delivery_date=delivery_date,
        status=OrderStatus.DRAFT,
        sync_status=SyncStatus.PENDING,
        total_amount_excl_vat=Decimal("30.00"),
        total_vat=Decimal("7.50"),
        total_amount_incl_vat=Decimal("37.50"),
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        tenant_id=tenant.id,
        order_id=order.id,
        product_id=product.id,
        quantity=1,
        unit_price=Decimal("30.00"),
        vat_rate=Decimal("25.00"),
        line_amount_excl_vat=Decimal("30.00"),
        line_vat=Decimal("7.50"),
        line_amount_incl_vat=Decimal("37.50"),
    )
    db_session.add(line)
    db_session.commit()

    customer.susoft_price_tier = CustomerPriceTier.PRICE_2
    db_session.commit()

    asyncio.run(propagate_customer_price_tier_change(customer.id, tenant.id))

    db_session.refresh(line)
    db_session.refresh(order)
    assert line.unit_price == Decimal("24.00")
    assert line.vat_rate == Decimal("15.00")
    assert line.line_amount_excl_vat == Decimal("24.00")
    assert line.line_vat == Decimal("3.60")
    assert line.line_amount_incl_vat == Decimal("27.60")
    assert order.total_amount_excl_vat == Decimal("24.00")
    assert order.total_vat == Decimal("3.60")
    assert order.total_amount_incl_vat == Decimal("27.60")
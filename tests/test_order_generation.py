"""Tester for ordregenerering — _generate_for_date."""
from datetime import date
from decimal import Decimal

from app.api.orders import _generate_for_date
from app.models import Order, OrderDateOverride, OrderStatus, SyncStatus


class TestGenerateForDate:
    def test_skips_closed_days(self, db_session, tenant, template_with_item):
        """Helligdager skal ikke generere ordre."""
        result = _generate_for_date(db_session, tenant.id, date(2026, 5, 17))
        assert result["reason"] == "closed_day"
        assert result["created_count"] == 0
        assert result["created"] == []

    def test_generates_order_on_matching_weekday(self, db_session, tenant, customer, template_with_item):
        """Tirsdag (day_of_week=2) skal generere ordre fra mal."""
        # Tirsdag 5. mai 2026
        target = date(2026, 5, 5)
        assert target.weekday() + 1 == 2  # Sanity-sjekk
        result = _generate_for_date(db_session, tenant.id, target)
        assert result.get("reason") != "closed_day"
        # Skal ha laget en ordre for kunden
        order = db_session.query(Order).filter(
            Order.tenant_id == tenant.id,
            Order.customer_id == customer.id,
            Order.delivery_date == target,
        ).first()
        assert order is not None
        assert len(order.lines) == 1
        assert order.lines[0].quantity == 5

    def test_skips_when_order_already_exists(self, db_session, tenant, customer, template_with_item):
        """Ikke generer dobbel ordre for samme dato."""
        target = date(2026, 5, 12)  # En annen tirsdag
        # Først kjøring
        _generate_for_date(db_session, tenant.id, target)
        db_session.commit()
        # Andre kjøring
        result = _generate_for_date(db_session, tenant.id, target)
        assert any(s.get("reason") == "already_exists" for s in result["skipped"])

    def test_skips_when_multiple_orders_already_exist(self, db_session, tenant, customer, template_with_item):
        """Eksisterende dubletter i data skal ikke krasje periodeplan-generering."""
        target = date(2026, 5, 19)
        order1 = Order(
            tenant_id=tenant.id,
            customer_id=customer.id,
            delivery_date=target,
            status=OrderStatus.DRAFT,
            sync_status=SyncStatus.PENDING,
            total_amount_excl_vat=Decimal("0.00"),
            total_vat=Decimal("0.00"),
            total_amount_incl_vat=Decimal("0.00"),
        )
        order2 = Order(
            tenant_id=tenant.id,
            customer_id=customer.id,
            delivery_date=target,
            status=OrderStatus.DRAFT,
            sync_status=SyncStatus.PENDING,
            total_amount_excl_vat=Decimal("0.00"),
            total_vat=Decimal("0.00"),
            total_amount_incl_vat=Decimal("0.00"),
        )
        db_session.add_all([order1, order2])
        db_session.commit()

        result = _generate_for_date(db_session, tenant.id, target)

        skipped = [s for s in result["skipped"] if s.get("reason") == "already_exists"]
        assert skipped
        assert skipped[0]["order_id"] == order1.id

    def test_no_order_on_wrong_weekday(self, db_session, tenant, customer, template_with_item):
        """Onsdag (day_of_week=3) — mal har ingen items, ingen ordre."""
        target = date(2026, 5, 6)  # Onsdag
        assert target.weekday() + 1 == 3
        _generate_for_date(db_session, tenant.id, target)
        order = db_session.query(Order).filter(
            Order.tenant_id == tenant.id,
            Order.customer_id == customer.id,
            Order.delivery_date == target,
        ).first()
        assert order is None

    def test_override_changes_quantity(self, db_session, tenant, customer, product, template_with_item):
        """OrderDateOverride skal overstyre quantity."""
        target = date(2026, 5, 19)  # Tirsdag
        override = OrderDateOverride(
            tenant_id=tenant.id,
            customer_id=customer.id,
            product_id=product.id,
            override_date=target,
            quantity=99,
        )
        db_session.add(override)
        db_session.commit()
        _generate_for_date(db_session, tenant.id, target)
        order = db_session.query(Order).filter(
            Order.customer_id == customer.id,
            Order.delivery_date == target,
        ).first()
        assert order is not None
        assert order.lines[0].quantity == 99

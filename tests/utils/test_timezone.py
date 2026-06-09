import datetime as dt
from zoneinfo import ZoneInfo

from app.utils import timezone

OSLO_TZ = ZoneInfo("Europe/Oslo")


def test_is_order_locked_for_editing_before_cutoff_winter(monkeypatch) -> None:
    delivery_date = dt.date(2026, 1, 16)
    mocked_now = dt.datetime(2026, 1, 15, 9, 59, tzinfo=OSLO_TZ)

    monkeypatch.setattr(timezone, "_now_in_oslo", lambda: mocked_now)

    assert timezone.is_order_locked_for_editing(delivery_date) is False


def test_is_order_locked_for_editing_after_cutoff_winter(monkeypatch) -> None:
    delivery_date = dt.date(2026, 1, 16)
    mocked_now = dt.datetime(2026, 1, 15, 10, 1, tzinfo=OSLO_TZ)

    monkeypatch.setattr(timezone, "_now_in_oslo", lambda: mocked_now)

    assert timezone.is_order_locked_for_editing(delivery_date) is True


def test_is_order_locked_for_editing_before_cutoff_summer(monkeypatch) -> None:
    delivery_date = dt.date(2026, 7, 2)
    mocked_now = dt.datetime(2026, 7, 1, 9, 59, tzinfo=OSLO_TZ)

    monkeypatch.setattr(timezone, "_now_in_oslo", lambda: mocked_now)

    assert timezone.is_order_locked_for_editing(delivery_date) is False


def test_is_order_locked_for_editing_after_cutoff_summer(monkeypatch) -> None:
    delivery_date = dt.date(2026, 7, 2)
    mocked_now = dt.datetime(2026, 7, 1, 10, 1, tzinfo=OSLO_TZ)

    monkeypatch.setattr(timezone, "_now_in_oslo", lambda: mocked_now)

    assert timezone.is_order_locked_for_editing(delivery_date) is True
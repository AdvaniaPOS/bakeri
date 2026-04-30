"""Tester for cut-off-logikken (15:00 dagen før levering, Oslo-tid)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.time_utils import is_past_cutoff, cutoff_datetime_for

OSLO = ZoneInfo("Europe/Oslo")


class TestCutoff:
    def test_cutoff_is_15_00_day_before(self):
        delivery = date(2026, 5, 12)  # Tirsdag
        cutoff = cutoff_datetime_for(delivery)
        assert cutoff.date() == date(2026, 5, 11)  # Mandag
        assert cutoff.hour == 15
        assert cutoff.minute == 0

    def test_before_cutoff_not_locked(self):
        delivery = date(2026, 5, 12)
        # 14:59 dagen før — fortsatt åpen
        now = datetime(2026, 5, 11, 14, 59, tzinfo=OSLO)
        assert not is_past_cutoff(delivery, now=now)

    def test_at_cutoff_is_locked(self):
        delivery = date(2026, 5, 12)
        # Akkurat 15:00 — låst
        now = datetime(2026, 5, 11, 15, 0, tzinfo=OSLO)
        assert is_past_cutoff(delivery, now=now)

    def test_after_cutoff_is_locked(self):
        delivery = date(2026, 5, 12)
        now = datetime(2026, 5, 11, 16, 0, tzinfo=OSLO)
        assert is_past_cutoff(delivery, now=now)

    def test_two_days_before_not_locked(self):
        delivery = date(2026, 5, 12)
        now = datetime(2026, 5, 10, 23, 59, tzinfo=OSLO)
        assert not is_past_cutoff(delivery, now=now)

    def test_delivery_day_is_locked(self):
        delivery = date(2026, 5, 12)
        now = datetime(2026, 5, 12, 7, 0, tzinfo=OSLO)
        assert is_past_cutoff(delivery, now=now)

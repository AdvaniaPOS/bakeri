"""Tester for nasjonale stengte dager (helligdager + jul-/påskeaften)."""
from datetime import date

from app.holidays_no import is_closed_day, closed_dates


class TestHolidaysNo:
    def test_first_of_may_is_closed(self):
        assert is_closed_day(date(2026, 5, 1))

    def test_constitution_day_is_closed(self):
        assert is_closed_day(date(2026, 5, 17))

    def test_christmas_eve_is_closed(self):
        assert is_closed_day(date(2025, 12, 24))

    def test_christmas_day_is_closed(self):
        assert is_closed_day(date(2025, 12, 25))

    def test_new_years_day_is_closed(self):
        assert is_closed_day(date(2026, 1, 1))

    def test_easter_sunday_2026_is_closed(self):
        # Påskedag 2026 = 5. april
        assert is_closed_day(date(2026, 4, 5))

    def test_easter_eve_2026_is_closed(self):
        # Påskeaften 2026 = 4. april
        assert is_closed_day(date(2026, 4, 4))

    def test_good_friday_2026_is_closed(self):
        # Langfredag 2026 = 3. april
        assert is_closed_day(date(2026, 4, 3))

    def test_ascension_day_2026_is_closed(self):
        # Kristi himmelfartsdag 2026 = 14. mai
        assert is_closed_day(date(2026, 5, 14))

    def test_pentecost_2026_is_closed(self):
        # Pinsedag 2026 = 24. mai
        assert is_closed_day(date(2026, 5, 24))

    def test_normal_tuesday_is_open(self):
        # Tirsdag 6. mai 2025 — vanlig hverdag
        assert not is_closed_day(date(2025, 5, 6))

    def test_normal_weekend_is_open(self):
        # Lørdag 4. oktober 2025
        assert not is_closed_day(date(2025, 10, 4))

    def test_closed_dates_returns_frozenset(self):
        result = closed_dates(2026)
        assert isinstance(result, frozenset)
        assert len(result) >= 12  # Minst 12 lukkede dager pr år

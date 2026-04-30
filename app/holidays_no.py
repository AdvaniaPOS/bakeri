"""
Norske helligdager + julaften/påskeaften.

Brukes til å hindre auto-generering av ordrer på dager bakeriet er stengt.
Beregner påskedato med Anonymous Gregorian-algoritmen — ingen ekstern dep.
"""
from datetime import date, timedelta
from functools import lru_cache


def _easter_sunday(year: int) -> date:
    """1. påskedag for et gitt år (Gregoriansk kalender)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=32)
def closed_dates(year: int) -> frozenset[date]:
    """Sett med datoer bakeriet anses som stengt (helligdager + aftener)."""
    easter = _easter_sunday(year)
    dates = {
        date(year, 1, 1),                    # Nyttårsdag
        easter - timedelta(days=3),          # Skjærtorsdag
        easter - timedelta(days=2),          # Langfredag
        easter - timedelta(days=1),          # Påskeaften
        easter,                              # 1. påskedag
        easter + timedelta(days=1),          # 2. påskedag
        date(year, 5, 1),                    # Arbeidernes dag
        date(year, 5, 17),                   # Grunnlovsdag
        easter + timedelta(days=39),         # Kristi himmelfartsdag
        easter + timedelta(days=49),         # 1. pinsedag
        easter + timedelta(days=50),         # 2. pinsedag
        date(year, 12, 24),                  # Julaften
        date(year, 12, 25),                  # 1. juledag
        date(year, 12, 26),                  # 2. juledag
    }
    return frozenset(dates)


def is_closed_day(d: date) -> bool:
    """True hvis bakeriet anses stengt på denne datoen."""
    return d in closed_dates(d.year)

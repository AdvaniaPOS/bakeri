"""
Tidssone-hjelpere for hele applikasjonen.

REGEL: All forretningslogikk skal bruke `now_oslo()` (tidssone-bevisst, Europe/Oslo).
`datetime.now()` og `datetime.utcnow()` uten tzinfo er bugs som venter på sommertid.

For lagring i DB:
- Vi bruker fortsatt naive datetime i DB for bakoverkompatibilitet med eksisterende SQLite-data.
- Konverter via `to_naive_utc()` rett før lagring hvis trengs.
- Cut-off-sammenligninger gjøres ALLTID i Oslo-tid.
"""
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

OSLO_TZ = ZoneInfo("Europe/Oslo")
UTC_TZ = ZoneInfo("UTC")


def now_oslo() -> datetime:
    """Returner nåværende tid i Europe/Oslo (tidssone-bevisst)."""
    return datetime.now(tz=OSLO_TZ)


def now_utc() -> datetime:
    """Returner nåværende tid i UTC (tidssone-bevisst)."""
    return datetime.now(tz=UTC_TZ)


def today_oslo() -> date:
    """Returner dagens dato i Oslo (slik at midnatt UTC ikke gir feil dato)."""
    return now_oslo().date()


def to_oslo(dt: datetime) -> datetime:
    """Konverter en datetime til Oslo-tid. Antar UTC hvis tzinfo mangler."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(OSLO_TZ)


def to_naive_utc(dt: datetime) -> datetime:
    """Konverter til naiv UTC for lagring i DB."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC_TZ).replace(tzinfo=None)


# Cut-off-konfigurasjon (Oslo-tid)
CUTOFF_HOUR = 15
CUTOFF_MINUTE = 0


def cutoff_datetime_for(delivery_date: date) -> datetime:
    """
    Beregn cut-off-tidspunkt for en gitt leveringsdato.
    Returnerer tidssone-bevisst datetime i Oslo-tid.

    Cut-off er kl. 15:00 dagen FØR levering.
    """
    cutoff_date = delivery_date - timedelta(days=1)
    return datetime.combine(cutoff_date, time(CUTOFF_HOUR, CUTOFF_MINUTE), tzinfo=OSLO_TZ)


def is_past_cutoff(delivery_date: date, now: datetime | None = None) -> bool:
    """
    Returner True hvis vi er forbi cut-off for denne leveringsdatoen.

    Dette er den autoritative kilden — ikke et DB-felt som krever Celery-jobb.
    """
    current = now or now_oslo()
    if current.tzinfo is None:
        current = current.replace(tzinfo=OSLO_TZ)
    return current >= cutoff_datetime_for(delivery_date)

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


# =============================================================================
# Konfigurerbar cutoff + tidligst mulig leveringsdato
# =============================================================================

DEFAULT_NON_DELIVERY_WEEKDAYS = [5, 6, 0]  # lør, søn, man
"""Standard ikke-leveringsdager. 0=mandag, 6=søndag (Python weekday())."""


def _tenant_cutoff(tenant_settings: dict | None) -> tuple[int, int]:
    """Hent konfigurerbar cutoff fra tenant.settings, default 15:00."""
    s = tenant_settings or {}
    h = s.get("cutoff_hour", CUTOFF_HOUR)
    m = s.get("cutoff_minute", CUTOFF_MINUTE)
    try:
        h = int(h); m = int(m)
        if not (0 <= h <= 23): h = CUTOFF_HOUR
        if not (0 <= m <= 59): m = CUTOFF_MINUTE
    except (TypeError, ValueError):
        h, m = CUTOFF_HOUR, CUTOFF_MINUTE
    return h, m


def _tenant_non_delivery_set(tenant_settings: dict | None) -> set[int]:
    """Hent ikke-leveringsdager fra tenant.settings (liste med Python weekday-int 0-6)."""
    s = tenant_settings or {}
    raw = s.get("non_delivery_weekdays", DEFAULT_NON_DELIVERY_WEEKDAYS)
    if not isinstance(raw, (list, tuple)):
        return set(DEFAULT_NON_DELIVERY_WEEKDAYS)
    out = set()
    for v in raw:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if 0 <= iv <= 6:
            out.add(iv)
    return out


def cutoff_datetime_for_tenant(delivery_date: date, tenant_settings: dict | None) -> datetime:
    h, m = _tenant_cutoff(tenant_settings)
    cutoff_date = delivery_date - timedelta(days=1)
    return datetime.combine(cutoff_date, time(h, m), tzinfo=OSLO_TZ)


def is_past_cutoff_tenant(delivery_date: date, tenant_settings: dict | None,
                          now: datetime | None = None) -> bool:
    current = now or now_oslo()
    if current.tzinfo is None:
        current = current.replace(tzinfo=OSLO_TZ)
    return current >= cutoff_datetime_for_tenant(delivery_date, tenant_settings)


def earliest_delivery_date(tenant_settings: dict | None,
                           production_days: int = 0,
                           now: datetime | None = None) -> date:
    """
    Beregn tidligst mulig leveringsdato gitt:
      - tenant cutoff (default 15:00)
      - tenant.non_delivery_weekdays (default lør/søn/man)
      - et minimum antall produksjonsdager (max på tvers av varene i ordren)

    Logikk:
      base_offset = 1 hvis vi er FØR cutoff i dag, ellers 2.
      effective_offset = base_offset + production_days
      Tell `effective_offset` framover fra i dag, hopp over ikke-leveringsdager.
    """
    current = now or now_oslo()
    if current.tzinfo is None:
        current = current.replace(tzinfo=OSLO_TZ)

    today = current.date()
    h, m = _tenant_cutoff(tenant_settings)
    cutoff_today = datetime.combine(today, time(h, m), tzinfo=OSLO_TZ)

    base_offset = 1 if current < cutoff_today else 2
    needed = base_offset + max(0, int(production_days or 0))
    skip = _tenant_non_delivery_set(tenant_settings)

    candidate = today
    counted = 0
    # Tell framover, hopp over non-delivery
    while counted < needed:
        candidate = candidate + timedelta(days=1)
        if candidate.weekday() in skip:
            continue
        counted += 1
    return candidate

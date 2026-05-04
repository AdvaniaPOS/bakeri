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


# delivery_cutoffs: liste av {dw, cw, h, m}
#   dw = delivery weekday (0=man..6=søn)
#   cw = cutoff weekday (0=man..6=søn) — må være FØR dw i uka (eller samme uke før dw)
#   h, m = klokkeslett (Oslo-tid)
# Mangler en weekday i lista = ingen levering den dagen.
DEFAULT_DELIVERY_CUTOFFS = [
    {"dw": 0, "cw": 3, "h": 15, "m": 0},  # Mandag ← Torsdag 15:00
    {"dw": 1, "cw": 4, "h": 15, "m": 0},  # Tirsdag ← Fredag 15:00
    {"dw": 2, "cw": 1, "h": 15, "m": 0},  # Onsdag ← Tirsdag 15:00
    {"dw": 3, "cw": 2, "h": 15, "m": 0},  # Torsdag ← Onsdag 15:00
    {"dw": 4, "cw": 3, "h": 15, "m": 0},  # Fredag ← Torsdag 15:00
]


def _delivery_schedule(tenant_settings: dict | None) -> dict[int, dict]:
    """Returner dict {delivery_weekday: rule} fra tenant.settings, default DEFAULT_DELIVERY_CUTOFFS."""
    s = tenant_settings or {}
    raw = s.get("delivery_cutoffs", DEFAULT_DELIVERY_CUTOFFS)
    if not isinstance(raw, list):
        raw = DEFAULT_DELIVERY_CUTOFFS
    out: dict[int, dict] = {}
    for r in raw:
        if not isinstance(r, dict):
            continue
        try:
            dw = int(r.get("dw", -1))
            cw = int(r.get("cw", -1))
            h = int(r.get("h", 15))
            m = int(r.get("m", 0))
        except (TypeError, ValueError):
            continue
        if not (0 <= dw <= 6 and 0 <= cw <= 6 and 0 <= h <= 23 and 0 <= m <= 59):
            continue
        out[dw] = {"dw": dw, "cw": cw, "h": h, "m": m}
    return out


def cutoff_for_delivery(delivery_date: date, tenant_settings: dict | None) -> datetime | None:
    """Beregn cutoff-tidspunkt for en gitt leveringsdato.

    Returnerer None hvis dagen ikke har en regel (= ikke leveringsdag).
    Cutoff defineres som siste forekomst av cutoff-ukedagen FØR (eller samme dag som)
    leveringsdatoen, men aldri leveringsdatoen selv.
    """
    schedule = _delivery_schedule(tenant_settings)
    rule = schedule.get(delivery_date.weekday())
    if not rule:
        return None
    # Antall dager bakover fra delivery_date til siste forekomst av rule.cw
    diff = (delivery_date.weekday() - rule["cw"]) % 7
    if diff == 0:
        diff = 7  # cutoff må være FØR leveringsdato
    cutoff_date = delivery_date - timedelta(days=diff)
    return datetime.combine(cutoff_date, time(rule["h"], rule["m"]), tzinfo=OSLO_TZ)


def is_past_cutoff_tenant(delivery_date: date, tenant_settings: dict | None,
                          now: datetime | None = None) -> bool:
    """True hvis bestillingsfristen for denne leveringsdatoen har passert
    (eller dagen ikke er en gyldig leveringsdag i det hele tatt)."""
    co = cutoff_for_delivery(delivery_date, tenant_settings)
    if co is None:
        return True  # ikke leveringsdag — blokker
    current = now or now_oslo()
    if current.tzinfo is None:
        current = current.replace(tzinfo=OSLO_TZ)
    return current >= co


def earliest_delivery_date(tenant_settings: dict | None,
                           production_days: int = 0,
                           now: datetime | None = None) -> date:
    """Tidligst mulig leveringsdato, gitt:
      - tenant.delivery_cutoffs (per-ukedag cutoff-skjema)
      - et minimum antall produksjonsdager (max på tvers av varene i ordren)

    Algoritme: gå framover fra i morgen; returner første dato D der:
      - D.weekday() har en regel i skjemaet
      - cutoff_for_delivery(D) er i framtiden ift. (now + production_days)
    Letingen avsluttes etter 21 dager (fail-safe).
    """
    current = now or now_oslo()
    if current.tzinfo is None:
        current = current.replace(tzinfo=OSLO_TZ)
    effective_now = current + timedelta(days=max(0, int(production_days or 0)))
    today = current.date()

    for offset in range(1, 22):
        d = today + timedelta(days=offset)
        co = cutoff_for_delivery(d, tenant_settings)
        if co is None:
            continue
        if effective_now < co:
            return d
    # Fallback: today + 14 dager
    return today + timedelta(days=14)

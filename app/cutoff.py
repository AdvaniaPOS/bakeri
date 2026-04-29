"""
Cut-off-vakt: sentralisert sjekk for om en ordre kan endres.

Tidligere lå dette som et statisk DB-felt (`is_locked`) som ble satt av en
Celery-jobb kl. 15:00. Det er en risiko: hvis Celery er nede, kan ordrer
endres etter cut-off.

Nå er sannheten kode-basert (computed) via `is_order_locked()`.
DB-feltet `is_locked` beholdes som revisjons-stempel (når ble den faktisk låst),
men det er IKKE autoritært for sjekken.
"""
from fastapi import HTTPException, status

from .time_utils import is_past_cutoff, now_oslo, to_naive_utc


def is_order_locked(order) -> bool:
    """
    Avgjør om en ordre er låst basert på cut-off-tid OG eksplisitt låsing.

    En ordre er låst hvis:
    - Cut-off-tidspunktet for leveringsdatoen er passert, ELLER
    - Den er manuelt/eksplisitt låst (f.eks. via emergency-lock eller etter
      vellykket sync til SuSoft).
    """
    if getattr(order, "is_locked", False):
        return True
    return is_past_cutoff(order.delivery_date)


def ensure_editable(order) -> None:
    """
    Sentral guard: kall denne fra ALLE muterende endepunkter før endringer.

    Kaster HTTP 423 (Locked) hvis ordren ikke kan endres.
    """
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ordre ikke funnet")

    if getattr(order, "is_deleted", False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ordre er slettet")

    if is_order_locked(order):
        # 423 Locked er korrekt HTTP-status for "ressursen er låst"
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"Ordren er låst. Cut-off var kl. 15:00 dagen før levering "
                f"({order.delivery_date}). Endringer er ikke tillatt."
            ),
        )


def stamp_locked_at(order) -> None:
    """
    Sett `locked_at` hvis cut-off er passert og det ikke allerede er stemplet.
    Kalles opportunistisk (f.eks. ved lesning), uavhengig av Celery.
    """
    if not order.is_locked and is_past_cutoff(order.delivery_date):
        order.is_locked = True
        order.locked_at = to_naive_utc(now_oslo())

"""Timezone-safe helpers for order editing cutoffs.

All cutoff comparisons are evaluated in Europe/Oslo to avoid bugs caused by
UTC server clocks, DST transitions, or naive datetimes.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

OSLO_TZ = ZoneInfo("Europe/Oslo")
DEFAULT_ORDER_EDIT_CUTOFF_TIME = dt.time(10, 0)


def _now_in_oslo() -> dt.datetime:
    """Return the current aware datetime in Europe/Oslo."""
    return dt.datetime.now(tz=OSLO_TZ)


def _validate_delivery_date(delivery_date: dt.date) -> None:
    if isinstance(delivery_date, dt.datetime) or not isinstance(delivery_date, dt.date):
        raise TypeError("delivery_date must be a datetime.date instance")


def _validate_cutoff_time(cutoff_time: dt.time) -> None:
    if not isinstance(cutoff_time, dt.time):
        raise TypeError("cutoff_time must be a datetime.time instance")
    if cutoff_time.tzinfo is not None:
        raise ValueError(
            "cutoff_time must be a naive wall-clock time interpreted in Europe/Oslo"
        )


def _validate_current_time(current_time: dt.datetime) -> dt.datetime:
    if not isinstance(current_time, dt.datetime):
        raise TypeError("current time provider must return a datetime.datetime instance")
    if current_time.tzinfo is None:
        raise ValueError("current time must be timezone-aware")
    return current_time.astimezone(OSLO_TZ)


def cutoff_datetime_for_editing(
    delivery_date: dt.date,
    cutoff_time: dt.time = DEFAULT_ORDER_EDIT_CUTOFF_TIME,
) -> dt.datetime:
    """Return the Oslo-aware cutoff datetime for editing an order."""

    _validate_delivery_date(delivery_date)
    _validate_cutoff_time(cutoff_time)

    cutoff_date = delivery_date - dt.timedelta(days=1)
    return dt.datetime.combine(cutoff_date, cutoff_time, tzinfo=OSLO_TZ)


def is_order_locked_for_editing_at(
    delivery_date: dt.date,
    current_time: dt.datetime,
    cutoff_time: dt.time = DEFAULT_ORDER_EDIT_CUTOFF_TIME,
) -> bool:
    """Evaluate the editing lock for a specific point in time."""

    normalized_current_time = _validate_current_time(current_time)
    cutoff_datetime = cutoff_datetime_for_editing(delivery_date, cutoff_time=cutoff_time)
    return normalized_current_time >= cutoff_datetime


def is_order_locked_for_editing(
    delivery_date: dt.date,
    cutoff_time: dt.time = DEFAULT_ORDER_EDIT_CUTOFF_TIME,
) -> bool:
    """Return whether an order is locked for editing.

    The lock happens at ``cutoff_time`` on the day before ``delivery_date``,
    evaluated strictly in Europe/Oslo. The default cutoff for this helper is
    10:00 Oslo time.
    """

    _validate_delivery_date(delivery_date)
    _validate_cutoff_time(cutoff_time)

    return is_order_locked_for_editing_at(
        delivery_date,
        current_time=_now_in_oslo(),
        cutoff_time=cutoff_time,
    )

"""The shop's clock: today, sales days and time zone (``STORE_TIMEZONE``).

Nothing here reads the time zone of the server or of the PostgreSQL session,
so results are the same wherever the API runs.

A sales day ``D`` is ``[D HH:00, D+1 HH:00)`` in store time, where ``HH`` is
``STORE_DAY_START_HOUR`` (0 by default: midnight to midnight).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator
from sqlalchemy import Date, Integer, cast, extract, func, literal, literal_column
from sqlalchemy.sql.elements import ColumnElement

from app.config.settings import settings


@lru_cache
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def store_zone() -> ZoneInfo:
    return _zone(settings.STORE_TIMEZONE)


def _utcnow() -> datetime:
    # The one place that reads the system clock; tests replace it.
    return datetime.now(timezone.utc)


def store_now() -> datetime:
    """The current time, aware, in store time."""
    return _utcnow().astimezone(store_zone())


def sales_day_of(moment: datetime) -> date:
    """The sales day an aware ``moment`` belongs to."""
    local = moment.astimezone(store_zone())
    return (local - timedelta(hours=settings.STORE_DAY_START_HOUR)).date()


def store_today() -> date:
    """Today's sales day (document numbers, "today" in reports)."""
    return sales_day_of(_utcnow())


def day_start(d: date) -> datetime:
    """When sales day ``d`` starts, aware, in store time."""
    return datetime.combine(d, time(settings.STORE_DAY_START_HOUR), tzinfo=store_zone())


def store_day_range(d_from: date, d_to: date | None = None) -> tuple[datetime, datetime]:
    """``[start of d_from, start of the day after d_to)``; compare a
    timestamptz with ``>= start`` and ``< end`` so its index can be used."""
    return day_start(d_from), day_start((d_to or d_from) + timedelta(days=1))


def in_store_days(column, d_from: date | None, d_to: date | None) -> list[ColumnElement]:
    """WHERE clauses: ``column`` falls on sales days d_from..d_to (either may be None)."""
    clauses = []
    if d_from is not None:
        clauses.append(column >= day_start(d_from))
    if d_to is not None:
        clauses.append(column < day_start(d_to + timedelta(days=1)))
    return clauses


def _tz_literal():
    # Rendered inline so the same expression can appear in SELECT and GROUP BY
    # (two bound parameters would be two different expressions to PostgreSQL).
    return literal(settings.STORE_TIMEZONE, literal_execute=True)


def store_local(column) -> ColumnElement:
    """``column AT TIME ZONE STORE_TIMEZONE``: wall-clock time at the shop."""
    return func.timezone(_tz_literal(), column)


def store_sales_day(column) -> ColumnElement:
    """The sales day of a timestamptz ``column``, as a SQL date."""
    local = store_local(column)
    if settings.STORE_DAY_START_HOUR:
        # An int 1-23 (validated in settings), so it is safe to inline.
        local = local - literal_column(f"interval '{int(settings.STORE_DAY_START_HOUR)} hours'")
    return cast(local, Date)


def store_hour(column) -> ColumnElement:
    """The hour (0-23) on the shop's wall clock of a timestamptz ``column``."""
    return cast(extract("hour", store_local(column)), Integer)


def as_store_time(value: datetime) -> datetime:
    """A datetime sent without an offset is store time; one with an offset is kept."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=store_zone())
    return value


#: A request datetime: ``2026-11-01T00:00`` means midnight at the shop.
StoreDateTime = Annotated[datetime, AfterValidator(as_store_time)]

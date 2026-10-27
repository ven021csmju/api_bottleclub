"""The shop's clock (app/shared/clock.py) never depends on the server's time zone."""
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from app.config.settings import Settings, settings
from app.shared import clock

BKK = timedelta(hours=7)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.fixture()
def now(monkeypatch):
    """Set the clock: ``now("2026-10-27T03:30")`` (UTC)."""
    def _set(text: str) -> None:
        monkeypatch.setattr(clock, "_utcnow", lambda: utc(text))
    return _set


@pytest.fixture()
def day_start_hour(monkeypatch):
    def _set(hour: int) -> None:
        monkeypatch.setattr(settings, "STORE_DAY_START_HOUR", hour)
    return _set


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert (s.STORE_TIMEZONE, s.STORE_DAY_START_HOUR) == ("Asia/Bangkok", 0)

    @pytest.mark.parametrize("name", ["Asia/Bangkk", "", "Asia/Bangkok'; drop", "Asia Bangkok", "../etc/passwd"])
    def test_an_unknown_time_zone_does_not_start(self, name):
        with pytest.raises(ValidationError, match="STORE_TIMEZONE"):
            Settings(STORE_TIMEZONE=name)

    @pytest.mark.parametrize("hour", [-1, 24])
    def test_day_start_hour_is_0_to_23(self, hour):
        with pytest.raises(ValidationError, match="STORE_DAY_START_HOUR"):
            Settings(STORE_DAY_START_HOUR=hour)


class TestToday:
    def test_bangkok_date_while_utc_is_still_the_day_before(self, now):
        now("2026-10-26T17:30")  # 00:30 on the 27th in Bangkok
        assert clock.store_today() == date(2026, 10, 27)

    def test_morning_in_bangkok(self, now):
        now("2026-10-27T03:30")  # 10:30 Bangkok, 23:30 the day before in New York
        assert clock.store_today() == date(2026, 10, 27)
        assert clock.store_now().utcoffset() == BKK
        assert clock.store_now().hour == 10

    @pytest.mark.parametrize("moment, day", [
        ("2026-10-27T16:59:59", date(2026, 10, 27)),  # 23:59:59 Bangkok
        ("2026-10-27T17:00:00", date(2026, 10, 28)),  # 00:00 Bangkok
    ])
    def test_midnight_edge(self, now, moment, day):
        now(moment)
        assert clock.store_today() == day

    @pytest.mark.parametrize("moment, day", [
        ("2026-10-27T21:59:59", date(2026, 10, 27)),  # 04:59:59 on the 28th, Bangkok
        ("2026-10-27T22:00:00", date(2026, 10, 28)),  # 05:00 on the 28th, Bangkok
    ])
    def test_day_start_hour_5(self, now, day_start_hour, moment, day):
        day_start_hour(5)
        now(moment)
        assert clock.store_today() == day


class TestDayRange:
    def test_one_day_is_bangkok_midnight_to_midnight(self):
        start, end = clock.store_day_range(date(2026, 10, 27))
        assert start == utc("2026-10-26T17:00") and end == utc("2026-10-27T17:00")
        assert start.utcoffset() == BKK

    def test_range_ends_at_the_start_of_the_day_after_d_to(self):
        start, end = clock.store_day_range(date(2026, 10, 1), date(2026, 10, 31))
        assert start == utc("2026-09-30T17:00") and end == utc("2026-10-31T17:00")

    def test_day_start_hour_5(self, day_start_hour):
        day_start_hour(5)
        start, end = clock.store_day_range(date(2026, 10, 28))
        assert start == utc("2026-10-27T22:00") and end == utc("2026-10-28T22:00")
        assert clock.sales_day_of(utc("2026-10-27T21:59:59")) == date(2026, 10, 27)
        assert clock.sales_day_of(utc("2026-10-27T22:00")) == date(2026, 10, 28)


class TestRequestDatetime:
    adapter = TypeAdapter(clock.StoreDateTime)

    def test_without_offset_is_store_time(self):
        value = self.adapter.validate_python("2026-11-01T00:00:00")
        assert value == utc("2026-10-31T17:00")
        assert value.utcoffset() == BKK

    @pytest.mark.parametrize("text, expected", [
        ("2026-11-01T00:00:00Z", "2026-11-01T00:00"),
        ("2026-11-01T00:00:00-04:00", "2026-11-01T04:00"),
    ])
    def test_with_offset_is_kept(self, text, expected):
        assert self.adapter.validate_python(text) == utc(expected)


class TestSql:
    """The SQL expressions name the store time zone and inline it."""

    def _sql(self, expr) -> str:
        from sqlalchemy.dialects import postgresql
        return str(expr.compile(dialect=postgresql.psycopg.dialect(), compile_kwargs={"literal_binds": True}))

    def test_sales_day(self):
        from app.db.models import Order
        assert self._sql(clock.store_sales_day(Order.completed_at)) == (
            "CAST(timezone('Asia/Bangkok', orders.completed_at) AS DATE)"
        )

    def test_sales_day_with_start_hour(self, day_start_hour):
        from app.db.models import Order
        day_start_hour(5)
        assert self._sql(clock.store_sales_day(Order.completed_at)) == (
            "CAST(timezone('Asia/Bangkok', orders.completed_at) - interval '5 hours' AS DATE)"
        )

    def test_hour(self):
        from app.db.models import Order
        assert "timezone('Asia/Bangkok', orders.created_at)" in self._sql(clock.store_hour(Order.created_at))


def test_coupon_dates_without_offset_are_bangkok_midnight():
    from app.domains.coupons.schemas import CouponCreate

    coupon = CouponCreate(code="NOV", promotion_id=1,
                          start_date="2026-11-01T00:00:00", end_date="2026-11-30T23:59:59")
    assert coupon.start_date == utc("2026-10-31T17:00")
    assert coupon.end_date == utc("2026-11-30T16:59:59")

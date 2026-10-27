"""Every date/time column's SQL type matches its Python type hint (offline).

payment_verifications.ocr_time was declared DateTime with a ``time`` hint;
the code wrote a time, which a timestamp column refuses (Phase 36h).
"""
import datetime
import typing

from sqlalchemy import Date, DateTime, Time

from app.db.models import Base

SQL_TYPE = {datetime.datetime: DateTime, datetime.date: Date, datetime.time: Time}


def _hint(cls: type, attribute: str) -> type | None:
    """The Python type inside ``Mapped[... | None]``."""
    hint = typing.get_type_hints(cls)[attribute]
    (inner,) = typing.get_args(hint)
    kinds = [t for t in typing.get_args(inner) or (inner,) if t is not type(None)]
    return kinds[0] if len(kinds) == 1 else None


def test_temporal_columns_match_their_type_hints():
    wrong = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        for attribute in mapper.column_attrs:
            (column,) = attribute.columns
            hinted = _hint(cls, attribute.key)
            temporal = isinstance(column.type, (Date, DateTime, Time))
            if hinted in SQL_TYPE or temporal:
                if SQL_TYPE.get(hinted) is not type(column.type):
                    wrong[f"{column.table.name}.{column.name}"] = (hinted, type(column.type).__name__)
    assert wrong == {}


def test_timestamps_have_a_time_zone():
    naive = [
        f"{t.name}.{c.name}"
        for t in Base.metadata.tables.values()
        for c in t.columns
        if isinstance(c.type, DateTime) and not c.type.timezone
    ]
    assert naive == []

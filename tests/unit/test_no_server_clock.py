"""Nothing in app/ reads the server's or the PostgreSQL session's time zone (offline).

Use app/shared/clock.py instead:
- ``date.today()``, ``datetime.today()``, ``datetime.now()`` without a tz,
  ``datetime.utcnow()``: the server's local date or a naive datetime;
  use ``store_today()``, ``store_now()`` or ``datetime.now(timezone.utc)``.
- ``cast(<timestamptz>, Date)``, ``func.date(...)``, ``extract(...)``: a date or
  hour in the session's time zone; use ``in_store_days()``,
  ``store_sales_day()`` or ``store_hour()``.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
#: The one module that builds these expressions, on store-local values.
CLOCK = APP / "shared" / "clock.py"


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def offences(source: str, in_clock: bool = False) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        line = f"{node.lineno}: {ast.unparse(node)}"
        if name in ("date.today", "datetime.today", "datetime.utcnow", "datetime.datetime.utcnow",
                    "datetime.date.today", "datetime.datetime.today"):
            found.append(line)
        elif name in ("datetime.now", "datetime.datetime.now"):
            tz = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "tz"), None)
            if tz is None or (isinstance(tz, ast.Constant) and tz.value is None):
                found.append(line)
        elif name in ("func.date", "sa.func.date", "sqlalchemy.func.date"):
            found.append(line)
        elif in_clock:
            continue
        elif name in ("cast", "sqlalchemy.cast", "sa.cast") and len(node.args) > 1 and _dotted(node.args[1]) in (
            "Date", "sqlalchemy.Date", "sa.Date", "DATE",
        ):
            found.append(line)
        elif name.endswith(".cast") and node.args and _dotted(node.args[0]) in ("Date", "sqlalchemy.Date"):
            found.append(line)
        elif name in ("extract", "func.extract", "sqlalchemy.extract", "func.date_part", "func.date_trunc"):
            found.append(line)
    return found


@pytest.mark.parametrize("snippet", [
    "date.today()",
    "datetime.today()",
    "datetime.now()",
    "datetime.now(None)",
    "datetime.datetime.now()",
    "datetime.utcnow()",
    "func.date(Order.created_at) >= x",
    "cast(Order.completed_at, Date)",
    "Order.completed_at.cast(Date)",
    "extract('hour', Order.created_at)",
    "func.date_trunc('day', Order.created_at)",
])
def test_the_guard_finds(snippet):
    assert offences(snippet)


@pytest.mark.parametrize("snippet", [
    "datetime.now(timezone.utc)",
    "datetime.now(tz=timezone.utc)",
    "store_today()",
    "cast(Order.grand_total, Numeric)",
])
def test_the_guard_allows(snippet):
    assert not offences(snippet)


def test_app_never_reads_the_server_clock_or_session_dates():
    found = {}
    for path in sorted(APP.rglob("*.py")):
        hits = offences(path.read_text(encoding="utf-8-sig"), in_clock=path == CLOCK)
        if hits:
            found[str(path.relative_to(APP.parent))] = hits
    assert not found, f"use app/shared/clock.py instead: {found}"

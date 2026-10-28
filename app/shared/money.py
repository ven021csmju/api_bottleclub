"""Spreading an order-level amount over the order's lines (Phase 38d)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def prorate(amount: Decimal, line_totals: list[Decimal]) -> list[Decimal]:
    """``amount`` split over the lines in proportion to each line's total, to
    the cent. The last line takes what the rounding left, so the parts add up
    to ``amount`` exactly.

    The one way the API spreads an order over its lines: what each line was
    really paid (refunds) and each line's share of the order's discounts
    (reports)."""
    if not line_totals:
        return []
    amount = Decimal(str(amount))
    lines = [Decimal(str(t)) for t in line_totals]
    total = sum(lines, Decimal("0"))
    if total == 0:
        parts = [Decimal("0.00")] * (len(lines) - 1)
    else:
        parts = [(amount * line / total).quantize(CENT, rounding=ROUND_HALF_UP) for line in lines[:-1]]
    parts.append((amount - sum(parts, Decimal("0"))).quantize(CENT, rounding=ROUND_HALF_UP))
    return parts

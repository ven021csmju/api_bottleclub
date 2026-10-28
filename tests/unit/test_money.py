"""prorate: an order-level amount spread over the lines (Phase 38d)."""
from decimal import Decimal

from app.shared.money import prorate

D = Decimal


def test_in_proportion_to_the_line_totals():
    assert prorate(D("100.00"), [D("300"), D("100")]) == [D("75.00"), D("25.00")]


def test_the_last_line_takes_the_rounding_and_the_parts_add_up():
    # 10 over 350 + 180: 6.6037… -> 6.60, the last line 3.40 (not 3.3962… -> 3.40 by luck)
    assert prorate(D("10.00"), [D("350"), D("180")]) == [D("6.60"), D("3.40")]
    # three equal lines: 3.33 + 3.33 + 3.34
    parts = prorate(D("10.00"), [D("1"), D("1"), D("1")])
    assert parts == [D("3.33"), D("3.33"), D("3.34")] and sum(parts) == D("10.00")


def test_many_lines_never_lose_a_cent():
    lines = [D("0.07"), D("19.99"), D("333.33"), D("0.01"), D("7.77"), D("1234.56")]
    for amount in (D("0.01"), D("0.99"), D("13.37"), D("100.00"), D("1595.73")):
        assert sum(prorate(amount, lines)) == amount


def test_one_line_takes_it_all_and_no_lines_take_nothing():
    assert prorate(D("42.00"), [D("420")]) == [D("42.00")]
    assert prorate(D("42.00"), []) == []


def test_lines_of_nothing_leave_it_on_the_last_line():
    assert prorate(D("0"), [D("0"), D("0")]) == [D("0.00"), D("0.00")]
    assert prorate(D("5.00"), [D("0"), D("0")]) == [D("0.00"), D("5.00")]


def test_accepts_numbers_from_the_database():
    assert prorate(160, [200.0]) == [D("160.00")]

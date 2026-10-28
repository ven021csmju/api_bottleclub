"""Reports when orders carry discounts (Phase 38d).

One definition in every report:
  gross_sales = before every discount, net_sales = gross_sales - discounts
  (typed in, on lines and on the order) - coupon_discounts = grand_total,
  before refunds. A line's revenue is its total less its share of the order's
  discounts (app.shared.money.prorate, the function refunds use), so the
  categories and products add up to net_sales.

Up to v0.1.13 financial gross_sales was the grand_total (discounts already
off) and net_sales took the typed-in discount off again; categories and
products were line totals, before the order's discount or coupon.

Sales of today, all at A (wine 350 in Wine, cheese 180 in Food):
  o1  wine + cheese, 10.00 typed off the order (ecommerce)  530 -> 520.00
      spread 6.60 / 3.40 (10 x 350/530 = 6.6037.., the cheese line takes the rest)
  o2  wine + cheese, coupon 33.33 off                        530 -> 496.67
      spread 22.01 / 11.32
  o3  wine + cheese, 5.00 typed off the cheese line          530 -> 525.00
  o4  wine                                                   350 -> 350.00
gross 1940.00, discounts 15.00, coupons 33.33, net 1891.67
Wine 343.40 + 327.99 + 350 + 350 = 1371.39, Food 176.60 + 168.68 + 175 = 520.28
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.shared.clock import store_now
from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

D = Decimal
GROSS, DISCOUNTS, COUPONS, NET = D("1940.00"), D("15.00"), D("33.33"), D("1891.67")
WINE, FOOD = D("1371.39"), D("520.28")


def _n(value) -> Decimal:
    return D(str(value)).quantize(D("0.01"))


@pytest.fixture()
def sold(client: TestClient, session: Session, world, shop, as_) -> dict:
    from app.db.models import Category, Coupon, Customer, Product

    wine_cat = Category(organization_id=world.org, name="Wine")
    food_cat = Category(organization_id=world.org, name="Food")
    customer = Customer(organization_id=world.org, first_name="Discount", loyalty_points_balance=0)
    session.add_all([wine_cat, food_cat, customer])
    session.flush()
    session.get(Product, shop.wine).category_id = wine_cat.id
    session.get(Product, shop.cheese).category_id = food_cat.id
    now = store_now()
    session.add(Coupon(organization_id=world.org, code="CENTS", discount_type="fixed", discount_value=D("33.33"),
                       start_date=now - timedelta(days=1), end_date=now + timedelta(days=7), max_uses=10))
    session.commit()

    ba = as_("ba_a", "A")
    both = [{"product_id": shop.wine, "quantity": 1}, {"product_id": shop.cheese, "quantity": 1}]

    def order(**body) -> dict:
        resp = client.post(f"{API}/orders/", headers=idem(ba), json={"branch_id": world.A, **body})
        assert resp.status_code in (200, 201), resp.text
        return resp.json()["data"]

    o1 = order(items=both, discount_amount="10.00", order_source="ecommerce")
    resp = client.post(f"{API}/payments/", headers=idem(ba),
                       json={"order_id": o1["id"], "payment_method": "bank_transfer", "amount": "520.00"})
    assert resp.status_code in (200, 201), resp.text
    o2 = order(items=both, customer_id=customer.id, coupon_code="CENTS")
    o3 = order(items=[both[0], {**both[1], "discount_amount": "5.00"}])
    o4 = order(items=both[:1])
    for o, due in ((o2, "496.67"), (o3, "525.00"), (o4, "350.00")):
        assert D(o["grand_total"]) == D(due)
        assert checkout(client, ba, o["id"], ("cash", due)).status_code == 200
    return {"day": now.date().isoformat(), "o1": o1}


def _get(client, as_, path):
    resp = client.get(API + path, headers=as_("sa", "A"))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _money(report) -> tuple:
    return tuple(_n(report[k]) for k in ("gross_sales", "discounts", "coupon_discounts", "net_sales"))


def test_financial_takes_each_discount_off_once(client, sold, as_):
    fin = _get(client, as_, f"/reports/financial?date_from={sold['day']}&date_to={sold['day']}")
    assert _money(fin) == (GROSS, DISCOUNTS, COUPONS, NET)
    assert [_money(d) for d in fin["daily"]] == [(GROSS, DISCOUNTS, COUPONS, NET)]
    assert (_n(fin["refunds"]), _n(fin["net_after_refunds"])) == (0, NET)
    assert sum(_n(v) for v in fin["payment_methods"].values()) == NET


def test_daily_summary_has_the_same_numbers(client, sold, as_):
    day = _get(client, as_, f"/reports/daily-summary?date={sold['day']}")
    assert _money(day) == (GROSS, DISCOUNTS, COUPONS, NET)
    assert (day["total_orders"], _n(day["total_revenue"]), _n(day["net_after_refunds"])) == (4, NET, NET)


def test_sales_categories_products_and_hours_add_up_to_net(client, sold, as_):
    sales = _get(client, as_, f"/reports/sales?date_from={sold['day']}&date_to={sold['day']}&group_by=category")
    assert _money(sales) == (GROSS, DISCOUNTS, COUPONS, NET)
    assert _n(sales["total_sales"]) == NET
    assert {c["category"]: (_n(c["revenue"]), c["qty"]) for c in sales["sales_by_category"]} == {
        "Wine": (WINE, 4), "Food": (FOOD, 3)}
    assert sum(_n(c["revenue"]) for c in sales["sales_by_category"]) == NET
    assert {p["product_name"]: (p["total_qty"], _n(p["total_revenue"])) for p in sales["top_products"]} == {
        "Money wine": (4, WINE), "Money cheese": (3, FOOD)}
    assert sum(_n(h["sales"]) for h in sales["sales_by_hour"]) == NET


def test_ecommerce_dashboard_is_net_too(client, sold, as_):
    dash = _get(client, as_, "/reports/ecommerce/dashboard")
    assert (_n(dash["sales_today"]), _n(dash["sales_this_month"])) == (D("520.00"), D("520.00"))
    assert {w["product_name"]: _n(w["total_revenue"]) for w in dash["top_selling_wines"]} == {
        "Money wine": D("343.40"), "Money cheese": D("176.60")}


def test_a_refund_is_the_line_share_the_reports_use_and_net_sales_keeps_it(client, sold, as_):
    """The cheese of o1 comes back: its refund is 176.60, the same share of
    the order the category report gave it. net_sales stays; net_after_refunds
    takes it off."""
    ba, o1 = as_("ba_a", "A"), sold["o1"]
    cheese = o1["items"][1]
    resp = client.post(f"{API}/returns/", headers=idem(ba), json={
        "order_id": o1["id"], "reason": "dropped",
        "items": [{"order_item_id": cheese["id"], "product_id": cheese["product_id"], "quantity": 1}]})
    assert resp.status_code in (200, 201), resp.text
    resp = client.put(f"{API}/returns/{resp.json()['data']['id']}/process", headers=ba)
    assert resp.status_code == 200, resp.text
    fin = _get(client, as_, f"/reports/financial?date_from={sold['day']}&date_to={sold['day']}")
    assert _money(fin) == (GROSS, DISCOUNTS, COUPONS, NET)
    assert (_n(fin["refunds"]), _n(fin["net_after_refunds"])) == (D("176.60"), NET - D("176.60"))
    day = _get(client, as_, f"/reports/daily-summary?date={sold['day']}")
    assert (_n(day["net_sales"]), _n(day["total_refunds"]), _n(day["net_after_refunds"])) == (
        NET, D("176.60"), NET - D("176.60"))

"""A coupon used in an order (Phase 38c, bug 13).

The system computes the discount from the subtotal; the coupon is checked
(dates in store time, uses in all and per customer, minimum, branch, its
promotion) and each use is recorded. Not with a typed-in discount. A
cancelled order gives the use back; a returned one keeps it.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.shared.clock import store_now
from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, on_hand, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def customers(session: Session, world) -> list[int]:
    from app.db.models import Customer

    rows = [Customer(organization_id=world.org, first_name=f"Coupon {n}", loyalty_points_balance=0)
            for n in range(3)]
    session.add_all(rows)
    session.commit()
    return [c.id for c in rows]


def coupon(session: Session, world, code: str, **extra) -> int:
    from app.db.models import Coupon

    now = store_now()
    values = dict(organization_id=world.org, code=code, discount_type="percent", discount_value=Decimal("10"),
                  start_date=now - timedelta(days=1), end_date=now + timedelta(days=7), max_uses=10)
    values.update(extra)
    row = Coupon(**values)
    session.add(row)
    session.commit()
    return row.id


def _order(client: TestClient, as_, world, shop, customer: int | None, code: str | None, qty: int = 2,
           who: str = "pos_a", **extra):
    body = {"branch_id": world.A, "items": [{"product_id": shop.wine, "quantity": qty}], **extra}
    if customer is not None:
        body["customer_id"] = customer
    if code is not None:
        body["coupon_code"] = code
    return client.post(f"{API}/orders/", headers=idem(as_(who, "A")), json=body)


def _uses(session: Session, coupon_id: int) -> tuple[int, int]:
    """(coupons.used_count, coupon_usages not released)."""
    from app.db.models import Coupon, CouponUsage

    session.expire_all()
    live = session.scalar(select(func.count()).select_from(CouponUsage).where(
        CouponUsage.coupon_id == coupon_id, CouponUsage.released_at.is_(None)))
    return session.get(Coupon, coupon_id).used_count, live


def test_a_percent_coupon_at_the_sale(client: TestClient, session: Session, world, shop, customers, as_):
    cid = coupon(session, world, "TEN", max_discount=Decimal("50"))
    resp = _order(client, as_, world, shop, customers[0], "TEN")
    order = resp.json()["data"]
    assert resp.status_code == 200, resp.text
    # 10% of 700 is 70, at most 50
    assert (Decimal(order["subtotal"]), Decimal(order["coupon_discount"]), Decimal(order["discount_amount"]),
            Decimal(order["grand_total"])) == (Decimal("700"), Decimal("50"), Decimal("0"), Decimal("650"))
    assert order["coupon_id"] == cid and _uses(session, cid) == (1, 1)
    assert checkout(client, as_("pos_a", "A"), order["id"], ("cash", "650.00")).status_code == 200


def test_a_fixed_coupon_at_checkout(client: TestClient, session: Session, world, shop, customers, as_):
    cid = coupon(session, world, "HUNDRED", discount_type="fixed", discount_value=Decimal("100"))
    other = coupon(session, world, "OTHER")
    order = _order(client, as_, world, shop, customers[0], None, qty=1).json()["data"]
    resp = checkout(client, as_("pos_a", "A"), order["id"], ("cash", "300.00"), coupon_code="HUNDRED")
    paid = resp.json()["data"]
    assert resp.status_code == 200, resp.text
    assert (Decimal(paid["coupon_discount"]), Decimal(paid["grand_total"]), Decimal(paid["change_amount"])) == (
        Decimal("100"), Decimal("250"), Decimal("50"))
    assert _uses(session, cid) == (1, 1)

    second = _order(client, as_, world, shop, customers[1], "HUNDRED", qty=1).json()["data"]
    resp = checkout(client, as_("pos_a", "A"), second["id"], ("cash", "250.00"), coupon_code="OTHER")
    assert (resp.status_code, resp.json()["code"]) == (409, "COUPON_ALREADY_APPLIED")
    assert _uses(session, other) == (0, 0)
    resp = checkout(client, as_("pos_a", "A"), second["id"], ("cash", "250.00"), coupon_code="HUNDRED")
    assert resp.status_code == 200, resp.text
    assert _uses(session, cid) == (2, 2)


REFUSED = {
    "COUPON_NOT_FOUND": ("NOPE", {}),
    "COUPON_INACTIVE": ("OFF", {"is_active": False}),
    "COUPON_EXPIRED": ("OLD", {"start_date": "-10d", "end_date": "-1h"}),
    "COUPON_NOT_STARTED": ("SOON", {"start_date": "+1h", "end_date": "+10d"}),
    "COUPON_WRONG_BRANCH": ("ATB", {"branch_id": "B"}),
    "COUPON_USED_UP": ("GONE", {"max_uses": 1, "used_count": 1}),
    "COUPON_MIN_ORDER": ("BIG", {"min_order_amount": Decimal("1000")}),
    "COUPON_HAS_NO_DISCOUNT": ("BLANK", {"discount_type": None, "discount_value": None}),
    "COUPON_PROMOTION_ENDED": ("PROMO", {"promotion": "-1h"}),
}


def _when(text: str):
    sign, n, unit = text[0], int(text[1:-1]), text[-1]
    delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
    return store_now() + (delta if sign == "+" else -delta)


@pytest.mark.parametrize("expected", sorted(REFUSED))
def test_a_coupon_that_cannot_be_used_is_422(client: TestClient, session: Session, world, shop, customers, as_,
                                              expected):
    from app.db.models import Order, Promotion

    code, extra = REFUSED[expected]
    extra = dict(extra)
    if "promotion" in extra:
        session.add(Promotion(id="ended-promo", title="Ended", description="x", image_url="/x.png",
                              ends_at=_when(extra.pop("promotion"))))
        session.commit()
        extra["promotion_id"] = "ended-promo"
    for key in ("start_date", "end_date"):
        if key in extra:
            extra[key] = _when(extra[key])
    if extra.get("branch_id") == "B":
        extra["branch_id"] = world.B
    if code != "NOPE":
        coupon(session, world, code, **extra)
    before = on_hand(session, world.A, shop.wine)

    resp = _order(client, as_, world, shop, customers[0], code)
    assert (resp.status_code, resp.json()["code"]) == (422, expected), resp.text
    session.rollback()  # what get_db's close does to the refused request's writes
    assert on_hand(session, world.A, shop.wine) == before
    assert session.scalar(select(func.count()).select_from(Order).where(Order.organization_id == world.org)) == 0


def test_a_coupon_needs_a_customer_and_counts_per_customer(client: TestClient, session: Session, world, shop,
                                                           customers, as_):
    cid = coupon(session, world, "ONCE", max_uses_per_customer=1)
    resp = _order(client, as_, world, shop, None, "ONCE")
    assert (resp.status_code, resp.json()["code"]) == (422, "COUPON_NEEDS_CUSTOMER")
    assert _order(client, as_, world, shop, customers[0], "ONCE").status_code == 200
    resp = _order(client, as_, world, shop, customers[0], "ONCE")
    assert (resp.status_code, resp.json()["code"]) == (422, "COUPON_CUSTOMER_LIMIT")
    assert _order(client, as_, world, shop, customers[1], "ONCE").status_code == 200
    assert _uses(session, cid) == (2, 2)


def test_not_with_a_typed_in_discount(client: TestClient, session: Session, world, shop, customers, as_):
    coupon(session, world, "TEN")
    for extra in ({"discount_amount": "20.00"},):
        resp = _order(client, as_, world, shop, customers[0], "TEN", who="ba_a", **extra)
        assert (resp.status_code, resp.json()["code"]) == (422, "COUPON_WITH_MANUAL_DISCOUNT"), resp.text
    body = {"branch_id": world.A, "customer_id": customers[0], "coupon_code": "TEN",
            "items": [{"product_id": shop.wine, "quantity": 2, "discount_amount": "10.00"}]}
    resp = client.post(f"{API}/orders/", headers=idem(as_("ba_a", "A")), json=body)
    assert (resp.status_code, resp.json()["code"]) == (422, "COUPON_WITH_MANUAL_DISCOUNT"), resp.text


def test_a_cancelled_order_gives_the_use_back(client: TestClient, session: Session, world, shop, customers, as_):
    cid = coupon(session, world, "LAST", max_uses=1)
    order = _order(client, as_, world, shop, customers[0], "LAST").json()["data"]
    assert _uses(session, cid) == (1, 1)
    resp = _order(client, as_, world, shop, customers[1], "LAST")
    assert resp.json()["code"] == "COUPON_USED_UP"

    resp = client.post(f"{API}/orders/{order['id']}/cancel", headers=as_("pos_a", "A"), json={"reason": "x"})
    assert resp.status_code == 200, resp.text
    assert _uses(session, cid) == (0, 0)
    assert _order(client, as_, world, shop, customers[1], "LAST").status_code == 200
    assert _uses(session, cid) == (1, 1)


def test_a_returned_order_keeps_the_use_and_refunds_what_was_paid(client: TestClient, session: Session, world,
                                                                    shop, customers, as_):
    cid = coupon(session, world, "FIFTY", discount_type="fixed", discount_value=Decimal("50"))
    order = _order(client, as_, world, shop, customers[0], "FIFTY").json()["data"]
    assert checkout(client, as_("pos_a", "A"), order["id"], ("cash", "650.00")).status_code == 200
    resp = client.post(f"{API}/returns/", headers=idem(as_("ba_a", "A")), json={
        "order_id": order["id"], "reason": "corked",
        "items": [{"order_item_id": order["items"][0]["id"], "product_id": shop.wine, "quantity": 1}]})
    assert resp.status_code in (200, 201), resp.text
    resp = client.put(f"{API}/returns/{resp.json()['data']['id']}/process", headers=as_("ba_a", "A"))
    assert resp.status_code == 200, resp.text
    refunds = client.get(f"{API}/refunds/?order_id={order['id']}", headers=as_("ba_a", "A")).json()["data"]
    refunds = refunds["refunds"] if isinstance(refunds, dict) else refunds
    assert [Decimal(r["refund_amount"]) for r in refunds] == [Decimal("325.00")]  # half of the 650 paid
    assert _uses(session, cid) == (1, 1)


def test_the_report_shows_coupon_discounts_apart(client: TestClient, session: Session, world, shop, customers,
                                                 as_):
    coupon(session, world, "TEN")
    by_coupon = _order(client, as_, world, shop, customers[0], "TEN").json()["data"]
    typed = _order(client, as_, world, shop, None, None, who="ba_a", discount_amount="30.00").json()["data"]
    for order, due in ((by_coupon, "630.00"), (typed, "670.00")):
        assert checkout(client, as_("ba_a", "A"), order["id"], ("cash", due)).status_code == 200
    day = store_now().date().isoformat()
    resp = client.get(f"{API}/reports/financial?date_from={day}&date_to={day}", headers=as_("ba_a", "A"))
    report = resp.json()["data"]
    assert resp.status_code == 200, resp.text
    assert (report["coupon_discounts"], report["discounts"]) == (70.0, 30.0)
    assert [(d["coupon_discounts"], d["discounts"]) for d in report["daily"]] == [(70.0, 30.0)]


def test_validate_tells_what_the_coupon_gives(client: TestClient, session: Session, world, customers, as_):
    coupon(session, world, "AT-A", branch_id=world.A, max_discount=Decimal("80"))
    url = f"{API}/coupons/validate"
    resp = client.post(url, headers=as_("pos_a", "A"), json={"code": "AT-A", "customer_id": customers[0]})
    data = resp.json()["data"]
    assert (resp.status_code, data["valid"], data["discount_type"], Decimal(data["discount_value"]),
            Decimal(data["max_discount"])) == (200, True, "percent", Decimal("10"), Decimal("80"))
    resp = client.post(url, headers=as_("pos_a", "A"),
                       json={"code": "AT-A", "customer_id": customers[0], "branch_id": world.B})
    assert (resp.json()["data"]["valid"], resp.json()["data"]["code"]) == (False, "COUPON_WRONG_BRANCH")


def test_creating_a_coupon(client: TestClient, session: Session, world, as_):
    from app.db.models import Promotion, UserRole

    session.add(UserRole(user_id=world.users["orgmgr"], role_id=world.roles["Superadmin"], branch_id=None))
    session.add(Promotion(id="summer", title="Summer", description="x", image_url="/s.png"))
    session.commit()
    base = {"discount_type": "percent", "discount_value": "15", "start_date": "2030-01-01T00:00:00",
            "end_date": "2030-02-01T00:00:00"}
    resp = client.post(f"{API}/coupons/", headers=as_("orgmgr"), json={"code": "SUMMER", "promotion_id": "summer",
                                                                       "branch_id": world.A, **base})
    assert resp.status_code == 201, resp.text
    assert (resp.json()["data"]["promotion_id"], resp.json()["data"]["branch_id"]) == ("summer", world.A)
    for body, status, code in (({"promotion_id": 1}, 422, "PROMOTION_NOT_FOUND"),
                               ({"discount_value": "150"}, 422, None),
                               ({"discount_type": None}, 422, None),
                               ({"branch_id": 999999999}, 404, None)):
        resp = client.post(f"{API}/coupons/", headers=as_("orgmgr"), json={**base, "code": "BAD", **body})
        assert resp.status_code == status, (body, resp.text)
        if code:
            assert resp.json()["code"] == code

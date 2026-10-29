"""Idempotency keys on the routes that take money or stock (Phase 38b, bug 6).

POST /orders/, POST /orders/{id}/checkout, POST /payments/ and POST /returns/:
no key -> 422; same key and body -> the first answer again (one order, stock
taken once); same key, other body -> 409; a key is the sender's, per route.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, drawers, new_order, on_hand, shop  # noqa: F401, WINE_PRICE  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

# Phase 46: cash is taken only in an open shift (409 SHIFT_REQUIRED).
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("drawers")]


def _order_body(world, shop, quantity: int = 2) -> dict:
    return {"branch_id": world.A, "items": [{"product_id": shop.wine, "quantity": quantity}]}


def _orders(session: Session, world) -> int:
    from app.db.models import Order

    session.expire_all()
    return session.scalar(select(func.count()).select_from(Order).where(Order.organization_id == world.org))


def _paid_order(client, as_, world, shop) -> dict:
    order = new_order(client, idem(as_("ba_a", "A")), world.A, [(shop.wine, 1)])
    assert checkout(client, idem(as_("ba_a", "A")), order["id"], ("cash", "350.00")).status_code == 200
    return order


def test_no_key_is_422_on_each_route(client: TestClient, session: Session, world, shop, as_):
    order = new_order(client, idem(as_("ba_a", "A")), world.A, [(shop.wine, 1)])
    paid = _paid_order(client, as_, world, shop)
    calls = [
        ("/orders/", _order_body(world, shop)),
        (f"/orders/{order['id']}/checkout", {"payments": [{"payment_method": "cash", "amount": "350.00"}]}),
        ("/payments/", {"order_id": order["id"], "payment_method": "cash", "amount": "350.00"}),
        ("/returns/", {"order_id": paid["id"], "reason": "no key",
                       "items": [{"order_item_id": paid["items"][0]["id"], "product_id": shop.wine, "quantity": 1}]}),
    ]
    before = _orders(session, world)
    for path, body in calls:
        resp = client.post(f"{API}{path}", headers=as_("ba_a", "A"), json=body)
        assert (resp.status_code, resp.json()["code"]) == (422, "IDEMPOTENCY_KEY_REQUIRED"), (path, resp.text)
    assert _orders(session, world) == before
    assert on_hand(session, world.A, shop.wine) == 48


def test_same_key_and_body_is_one_order_and_stock_taken_once(client: TestClient, session: Session, world, shop, as_):
    headers = idem(as_("pos_a", "A"))
    first = client.post(f"{API}/orders/", headers=headers, json=_order_body(world, shop))
    again = client.post(f"{API}/orders/", headers=headers, json=_order_body(world, shop))
    assert (first.status_code, again.status_code) == (200, 200), again.text
    assert first.json()["data"]["id"] == again.json()["data"]["id"]
    assert again.headers.get("Idempotent-Replayed") == "true" and "Idempotent-Replayed" not in first.headers
    # The tracking token is shown once; the replay keeps everything else.
    assert first.json()["data"]["tracking_token"] and again.json()["data"]["tracking_token"] is None
    assert {**first.json()["data"], "tracking_token": None} == again.json()["data"]
    assert _orders(session, world) == 1
    assert on_hand(session, world.A, shop.wine) == 48


def test_same_key_other_body_is_409(client: TestClient, session: Session, world, shop, as_):
    headers = idem(as_("pos_a", "A"))
    assert client.post(f"{API}/orders/", headers=headers, json=_order_body(world, shop, 2)).status_code == 200
    resp = client.post(f"{API}/orders/", headers=headers, json=_order_body(world, shop, 3))
    assert (resp.status_code, resp.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")
    assert (_orders(session, world), on_hand(session, world.A, shop.wine)) == (1, 48)


def test_a_key_is_the_senders_per_route(client: TestClient, session: Session, world, shop, as_):
    key = "same-till-key"
    for who in ("pos_a", "pos_a2"):
        resp = client.post(f"{API}/orders/", headers={**as_(who, "A"), "Idempotency-Key": key},
                           json=_order_body(world, shop))
        assert resp.status_code == 200 and "Idempotent-Replayed" not in resp.headers, (who, resp.text)
    order = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 1)])
    # The same key on another route is another request.
    resp = client.post(f"{API}/orders/{order['id']}/checkout", headers={**as_("pos_a", "A"), "Idempotency-Key": key},
                       json={"payments": [{"payment_method": "cash", "amount": "350.00"}]})
    assert resp.status_code == 200 and "Idempotent-Replayed" not in resp.headers, resp.text
    assert (_orders(session, world), on_hand(session, world.A, shop.wine)) == (3, 45)


def test_checkout_and_payment_replays_take_the_money_once(client: TestClient, session: Session, world, shop, as_):
    from app.db.models import Payment

    order = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 2)])
    second = new_order(client, idem(as_("pos_a", "A")), world.A, [(shop.wine, 1)])
    headers = idem(as_("pos_a", "A"))
    body = {"order_id": second["id"], "payment_method": "cash", "amount": "350.00"}
    one = client.post(f"{API}/payments/", headers=headers, json=body)
    two = client.post(f"{API}/payments/", headers=headers, json=body)
    assert (one.status_code, two.status_code) == (200, 200), two.text
    assert one.json()["data"]["id"] == two.json()["data"]["id"]
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == second["id"])) == 1

    headers = idem(as_("pos_a", "A"))
    one = checkout(client, headers, order["id"], ("cash", "700.00"))
    two = checkout(client, headers, order["id"], ("cash", "700.00"))
    assert (one.status_code, two.status_code) == (200, 200), two.text
    assert one.json()["data"] == two.json()["data"]
    assert session.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == order["id"])) == 1


def test_a_return_replay_is_one_return(client: TestClient, session: Session, world, shop, as_):
    from app.db.models import Return

    paid = _paid_order(client, as_, world, shop)
    headers = idem(as_("ba_a", "A"))
    body = {"order_id": paid["id"], "reason": "corked",
            "items": [{"order_item_id": paid["items"][0]["id"], "product_id": shop.wine, "quantity": 1}]}
    one = client.post(f"{API}/returns/", headers=headers, json=body)
    two = client.post(f"{API}/returns/", headers=headers, json=body)
    assert (one.status_code, two.status_code) == (200, 200), two.text
    assert one.json()["data"]["id"] == two.json()["data"]["id"]
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Return).where(Return.order_id == paid["id"])) == 1


def test_an_error_is_not_kept_and_a_key_lasts_24_hours(client: TestClient, session: Session, world, shop, as_):
    from app.db.models import IdempotencyKey

    headers = idem(as_("pos_a", "A"))
    wrong = {"branch_id": world.A, "items": [{"product_id": shop.wine, "quantity": 1, "unit_price": "1.00"}]}
    resp = client.post(f"{API}/orders/", headers=headers, json=wrong)
    assert (resp.status_code, resp.json()["code"]) == (422, "PRICE_MISMATCH")
    resp = client.post(f"{API}/orders/", headers=headers, json=wrong)
    assert resp.json()["code"] == "PRICE_MISMATCH"  # sent again, not 409

    headers = idem(as_("pos_a", "A"))
    assert client.post(f"{API}/orders/", headers=headers, json=_order_body(world, shop, 1)).status_code == 200
    kept = session.scalars(select(IdempotencyKey).where(
        IdempotencyKey.idempotency_key == headers["Idempotency-Key"])).one()
    assert timedelta(hours=23, minutes=59) < kept.expires_at - kept.created_at <= timedelta(hours=24, minutes=1)
    session.execute(update(IdempotencyKey).where(IdempotencyKey.id == kept.id)
                    .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    session.commit()
    resp = client.post(f"{API}/orders/", headers=headers, json=_order_body(world, shop, 1))
    assert resp.status_code == 200 and "Idempotent-Replayed" not in resp.headers
    assert _orders(session, world) == 2


def test_header_and_body_key_must_agree(client: TestClient, world, shop, as_):
    body = {**_order_body(world, shop), "idempotency_key": "body-key"}
    resp = client.post(f"{API}/orders/", headers={**as_("pos_a", "A"), "Idempotency-Key": "other"}, json=body)
    assert (resp.status_code, resp.json()["code"]) == (422, "IDEMPOTENCY_KEY_MISMATCH")
    # The body's key alone is enough on the order routes.
    assert client.post(f"{API}/orders/", headers=as_("pos_a", "A"), json=body).status_code == 200

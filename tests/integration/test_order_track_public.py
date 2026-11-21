"""POST /orders/track: a customer's tracking with no login, by the order (or
tracking) number and the phone or email of the order's customer."""
import pytest

from app.db.models import Customer, Order

TRACK = "/api/v1/orders/track"
FIELDS = {"order_number", "tracking_number", "status", "shipping_carrier", "updated_at"}


@pytest.fixture()
def shipped(session, seed_user):
    customer = Customer(
        organization_id=seed_user["org_id"], first_name="Somchai", last_name="Testlast",
        phone="081-234-5678", email="Buyer@Example.test",
    )
    session.add(customer)
    session.flush()
    order = Order(
        organization_id=seed_user["org_id"], branch_id=seed_user["branch_id"],
        user_id=seed_user["user_id"], customer_id=customer.id, order_number="ORD-TRACK-0001",
        order_source="ecommerce", status="paid", fulfillment_status="shipped",
        tracking_number="TH0000000001", shipping_carrier="Kerry", grand_total=1500,
        notes="private note",
    )
    session.add(order)
    session.flush()
    return order


@pytest.mark.parametrize("ref", ["ORD-TRACK-0001", "TH0000000001"])
@pytest.mark.parametrize("contact", ["0812345678", "081 234 5678", "+66812345678", "buyer@example.TEST"])
def test_ref_and_contact_answer_the_tracking_fields_only(client, shipped, ref, contact):
    resp = client.post(TRACK, json={"ref": ref, "contact": contact})

    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert set(body) == FIELDS
    assert body["order_number"] == "ORD-TRACK-0001"
    assert body["tracking_number"] == "TH0000000001"
    assert body["status"] == "paid"
    assert body["shipping_carrier"] == "Kerry"
    for leak in ("Somchai", "Testlast", "1500", "private note", "customer_id"):
        assert leak not in resp.text


@pytest.mark.parametrize("ref, contact", [
    ("ORD-TRACK-0001", "0899999999"),      # right order, wrong phone
    ("ORD-TRACK-0001", "other@example.test"),
    ("ORD-NOPE-0001", "0812345678"),       # right phone, no such order
    ("ORD-TRACK-0001", "12345"),            # not a phone
    ("ORD-TRACK", "0812345678"),            # a prefix of the number
])
def test_wrong_or_unknown_is_one_404(client, shipped, ref, contact):
    resp = client.post(TRACK, json={"ref": ref, "contact": contact})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Order not found"
    assert resp.json()["code"] == "NOT_FOUND"


def test_an_order_without_a_customer_is_never_found(client, session, shipped):
    shipped.customer_id = None
    session.flush()

    assert client.post(TRACK, json={"ref": "ORD-TRACK-0001", "contact": "0812345678"}).status_code == 404


def test_a_deleted_customer_is_never_found(client, session, shipped):
    from datetime import datetime, timezone

    session.get(Customer, shipped.customer_id).deleted_at = datetime.now(timezone.utc)
    session.flush()

    assert client.post(TRACK, json={"ref": "ORD-TRACK-0001", "contact": "0812345678"}).status_code == 404


def test_no_login_needed_and_the_staff_route_is_unchanged(client, shipped, auth_headers):
    # The staff GET /orders/track/{ref} still needs a login...
    assert client.get("/api/v1/orders/track/ORD-TRACK-0001").status_code == 401
    staff = client.get("/api/v1/orders/track/ORD-TRACK-0001", headers=auth_headers)
    assert staff.status_code == 200 and staff.json()["data"]["order_number"] == "ORD-TRACK-0001"
    # ...and GET /orders/{reference} is not shadowed by /orders/track.
    assert client.get("/api/v1/orders/ORD-TRACK-0001", headers=auth_headers).status_code == 200


def test_missing_fields_are_422(client):
    assert client.post(TRACK, json={"ref": "ORD-TRACK-0001"}).status_code == 422


def test_the_carrier_is_set_with_the_tracking_number(client, session, shipped, staff_headers):
    url = f"/api/v1/orders/{shipped.id}/tracking"
    resp = client.put(url, json={"tracking_number": "TH0000000002", "shipping_carrier": " Flash "},
                      headers=staff_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["shipping_carrier"] == "Flash"
    # Left out: unchanged.
    resp = client.put(url, json={"tracking_number": "TH0000000003"}, headers=staff_headers)
    assert resp.json()["data"]["shipping_carrier"] == "Flash"
    # "": cleared.
    resp = client.put(url, json={"tracking_number": "TH0000000003", "shipping_carrier": ""},
                      headers=staff_headers)
    assert resp.json()["data"]["shipping_carrier"] is None


def test_rate_limited_per_ip(client, shipped, monkeypatch):
    from app.middleware.rate_limit import limiter

    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    try:
        answers = [
            client.post(TRACK, json={"ref": "ORD-TRACK-0001", "contact": "0899999999"}).status_code
            for _ in range(21)
        ]
    finally:
        limiter.reset()
    assert answers[:20] == [404] * 20
    assert answers[20] == 429

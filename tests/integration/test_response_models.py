"""The routes that got a response_model in Phase 42 (item 5) answer as before:
same fields, amounts still JSON numbers."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.scope_fixtures import API, as_, orders, stock, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture()
def slip(session: Session, world, orders) -> int:
    from decimal import Decimal

    from app.db.models import PaymentVerification

    verification = PaymentVerification(order_id=orders["a1"], image_sha256="r" * 64, status="review",
                                       ocr_amount=Decimal("100.00"), ocr_reference="REF-RM-1",
                                       risk_score={"score": 0.25}, created_by=world.users["sa"])
    session.add(verification)
    session.commit()
    return verification.id


def test_a_verification(client: TestClient, world, slip, as_):
    resp = client.get(f"{API}/slip-verify/{slip}", headers=as_("ba_a", "A"))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert set(data) == {"id", "order_id", "payment_id", "ocr_bank", "ocr_amount", "ocr_reference", "ocr_date",
                         "ocr_sender_name", "ocr_receiver_name", "ocr_receiver_account", "image_sha256", "status",
                         "risk_score", "risk_signals", "failure_reason", "created_at"}
    assert (data["ocr_amount"], data["risk_score"], data["status"]) == (100.0, 0.25, "review")


def test_the_verifications_of_an_order(client: TestClient, world, orders, slip, as_):
    resp = client.get(f"{API}/slip-verify/order/{orders['a1']}", headers=as_("ba_a", "A"))
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["data"]
    assert set(row) == {"id", "order_id", "status", "risk_score", "ocr_amount", "ocr_reference", "created_at"}
    assert (row["id"], row["ocr_amount"], row["risk_score"], row["ocr_reference"]) == (slip, 100.0, 0.25, "REF-RM-1")


def test_a_balance_and_an_adjustment(client: TestClient, world, stock, as_):
    url = f"{API}/inventory/balances/{world.A}/{stock}"
    assert client.get(url, headers=as_("ba_a", "A")).json()["data"] == {"on_hand": 5, "reserved": 0, "available": 5}
    resp = client.post(f"{API}/inventory/adjust", headers=as_("ba_a", "A"),
                       json={"branch_id": world.A, "product_id": stock, "quantity_adjustment": 2, "reason": "count"})
    assert (resp.status_code, resp.json()["data"]) == (200, {"message": "Inventory adjusted successfully"})
    assert client.get(url, headers=as_("ba_a", "A")).json()["data"]["on_hand"] == 7

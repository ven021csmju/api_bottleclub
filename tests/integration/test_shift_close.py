"""Closing a shift works and counts the cash: open → cash in/out → close (shift close was 500 up to v0.1.5)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.integration.scope_fixtures import API, as_, shifts, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def test_open_move_cash_close_gives_the_expected_cash(client: TestClient, world, shifts, as_):
    headers = as_("ba_a", "A")
    body = {"branch_id": world.A, "register_id": world.data["free_register_A"], "opening_cash": "100.00"}
    resp = client.post(f"{API}/shifts/open", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    shift_id = resp.json()["data"]["id"]

    for movement_type, amount in [("cash_in", "50.00"), ("cash_out", "30.00")]:
        body = {"movement_type": movement_type, "amount": amount, "reason": "test"}
        resp = client.post(f"{API}/shifts/{shift_id}/cash-movements", json=body, headers=headers)
        assert resp.status_code == 201, resp.text

    resp = client.put(f"{API}/shifts/{shift_id}/close", json={"closing_cash": "115.00"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "closed"

    resp = client.get(f"{API}/shifts/{shift_id}/x-report", headers=headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()["data"]
    # 100 opening + 50 in - 30 out = 120 expected; 115 counted → 5 short.
    assert Decimal(report["expected_cash"]) == Decimal("120.00")
    assert Decimal(report["closing_cash"]) == Decimal("115.00")
    assert Decimal(report["cash_difference"]) == Decimal("-5.00")
    assert Decimal(report["cash_movements_in"]) == Decimal("50.00")
    assert Decimal(report["cash_movements_out"]) == Decimal("30.00")


def test_a_closed_shift_cannot_be_closed_again(client: TestClient, world, shifts, as_):
    headers = as_("ba_a", "A")
    assert client.put(f"{API}/shifts/{shifts['a2']}/close", json={"closing_cash": "100"}, headers=headers).status_code == 200
    assert client.put(f"{API}/shifts/{shifts['a2']}/close", json={"closing_cash": "100"}, headers=headers).status_code == 400

"""Inventory of a branch is read and adjusted only with the permission there (Phase 35c ②)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models import Inventory
from tests.integration.scope_fixtures import API, as_, stock, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("path", [
    "/inventory/balances/{b}/{p}",
    "/inventory/lots?branch_id={b}&product_id={p}",
    "/inventory/movements?branch_id={b}&product_id={p}",
])
def test_reads_of_another_branch_are_404(client: TestClient, world, stock, as_, path):
    assert client.get(API + path.format(b=world.B, p=stock), headers=as_("ba_a", "A")).status_code == 404
    assert client.get(API + path.format(b=world.A, p=stock), headers=as_("ba_a", "A")).status_code == 200
    assert client.get(API + path.format(b=world.B, p=stock), headers=as_("sa")).status_code == 200


@pytest.mark.parametrize("path", ["/inventory/balances", "/inventory/low-stock"])
def test_lists_cover_the_active_branch_or_an_allowed_branch_id(client: TestClient, world, stock, as_, path):
    def branches(headers, query: str = "") -> list:
        resp = client.get(API + path + query, headers=headers)
        assert resp.status_code == 200, resp.text
        return [row.get("branch_id", row.get("branch_name")) for row in resp.json()["data"]]

    assert branches(as_("ba_a", "A")) in ([world.A], ["Branch A"])
    assert branches(as_("sa", "B")) in ([world.B], ["Branch B"])
    assert client.get(f"{API}{path}?branch_id={world.B}", headers=as_("ba_a", "A")).status_code == 404
    resp = client.get(API + path, headers=as_("ba_a"))
    assert (resp.status_code, resp.json()["code"]) == (400, "BRANCH_REQUIRED")


def test_adjusting_another_branch_is_404(client: TestClient, session, world, stock, as_):
    def adjust(headers, where: str) -> int:
        body = {"branch_id": world.branch[where], "product_id": stock, "quantity_adjustment": 1, "reason": "count"}
        return client.post(f"{API}/inventory/adjust", json=body, headers=headers).status_code

    assert adjust(as_("ba_a", "A"), "B") == 404
    # Manager at A, Cashier (no inventory.adjust) at B.
    assert adjust(as_("mixed", "B"), "B") == 404
    assert adjust(as_("mixed", "A"), "A") == 200
    session.expire_all()
    assert {i.branch_id: i.on_hand for i in session.query(Inventory).filter_by(product_id=stock)} == {world.A: 6, world.B: 7}

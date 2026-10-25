"""Shifts of a branch need the permission there; a cashier reads only their own (Phase 35c ②③)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.scope_fixtures import API, as_, shifts, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def test_opening_a_shift_at_another_branch_is_404(client: TestClient, world, shifts, as_):
    def open_(headers, branch: int, register: int) -> int:
        body = {"branch_id": branch, "register_id": register, "opening_cash": "0"}
        return client.post(f"{API}/shifts/open", json=body, headers=headers).status_code

    assert open_(as_("ba_a", "A"), world.B, world.data["register_B"]) == 404
    assert open_(as_("ba_a", "A"), world.A, world.data["free_register_A"]) == 201


@pytest.mark.parametrize("method,path,body", [
    ("PUT", "/shifts/{s}/close", {"closing_cash": "100"}),
    ("POST", "/shifts/{s}/cash-movements", {"movement_type": "cash_in", "amount": "5", "reason": "float"}),
])
def test_closing_or_moving_cash_on_a_shift_of_another_branch_is_404(
    client: TestClient, world, shifts, as_, method, path, body
):
    resp = client.request(method, API + path.format(s=shifts["b1"]), json=body, headers=as_("ba_a", "A"))
    assert resp.status_code == 404
    resp = client.request(method, API + path.format(s=shifts["a2"]), json=body, headers=as_("ba_a", "A"))
    assert resp.status_code in (200, 201), resp.text


class TestXReport:
    def test_cashier_reads_only_their_own_shift(self, client: TestClient, world, shifts, as_):
        assert client.get(f"{API}/shifts/{shifts['a2']}/x-report", headers=as_("pos_a", "A")).status_code == 404
        assert client.get(f"{API}/shifts/{shifts['a1']}/x-report", headers=as_("pos_a", "A")).status_code == 200

    def test_branch_manager_reads_every_shift_of_their_branch_only(self, client: TestClient, world, shifts, as_):
        assert client.get(f"{API}/shifts/{shifts['b1']}/x-report", headers=as_("ba_a", "A")).status_code == 404
        assert client.get(f"{API}/shifts/{shifts['a2']}/x-report", headers=as_("ba_a", "A")).status_code == 200


class TestList:
    @staticmethod
    def _ids(client: TestClient, headers, query: str = "") -> set[int]:
        resp = client.get(f"{API}/shifts/{query}", headers=headers)
        assert resp.status_code == 200, resp.text
        return {s["id"] for s in resp.json()["data"]["shifts"]}

    def test_cashier_lists_their_own_shifts_manager_the_branch(self, client: TestClient, world, shifts, as_):
        assert self._ids(client, as_("pos_a", "A")) == {shifts["a1"]}
        assert self._ids(client, as_("ba_a", "A")) == {shifts["a1"], shifts["a2"]}
        assert self._ids(client, as_("sa"), f"?branch_id={world.B}") == {shifts["b1"]}

    def test_another_branch_is_404(self, client: TestClient, world, shifts, as_):
        assert client.get(f"{API}/shifts/?branch_id={world.B}", headers=as_("ba_a", "A")).status_code == 404
        assert client.get(f"{API}/shifts/", headers=as_("ba_a")).status_code == 401

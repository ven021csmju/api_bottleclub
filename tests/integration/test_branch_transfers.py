"""A transfer is reached from its source or destination branch (Phase 35c ②)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.scope_fixtures import API, as_, transfers, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _listed(client: TestClient, headers) -> set[str]:
    resp = client.get(f"{API}/transfers/", headers=headers)
    assert resp.status_code == 200, resp.text
    return {t["transfer_number"] for t in resp.json()["data"]["transfers"]}


def test_list_holds_transfers_from_or_to_the_callers_branches(client: TestClient, world, transfers, as_):
    assert _listed(client, as_("ba_a", "A")) == {"TR-AB"}
    assert _listed(client, as_("orgmgr")) == {"TR-AB", "TR-CB"}


def test_a_transfer_not_touching_the_callers_branches_is_404(client: TestClient, world, transfers, as_):
    assert client.get(f"{API}/transfers/{transfers['cb']}", headers=as_("ba_a", "A")).status_code == 404
    assert client.put(f"{API}/transfers/{transfers['cb']}/cancel", headers=as_("ba_a", "A")).status_code == 404
    assert client.get(f"{API}/transfers/{transfers['ab']}", headers=as_("ba_a", "A")).status_code == 200


def test_ship_from_the_source_receive_at_the_destination(client: TestClient, world, transfers, as_):
    url = f"{API}/transfers/{transfers['ab']}"
    receive = {"items": [{"transfer_item_id": 1, "quantity_received": 1}]}
    ship = {"items": [{"transfer_item_id": 1, "quantity_shipped": 1}]}

    # ba_a holds A, the source of AB, not B, its destination.
    resp = client.put(f"{url}/receive", json=receive, headers=as_("ba_a", "A"))
    assert (resp.status_code, resp.json()["detail"]) == (404, "Transfer not found")
    # Past the branch check; the made-up item id is then refused by the service.
    resp = client.put(f"{url}/ship", json=ship, headers=as_("ba_a", "A"))
    assert resp.json()["detail"] != "Transfer not found"
    resp = client.put(f"{url}/receive", json=receive, headers=as_("orgmgr"))
    assert resp.json()["detail"] != "Transfer not found"

"""Without orders.read_branch a cashier sees only their own orders (Phase 35c ③)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.scope_fixtures import API, as_, orders, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _listed(client: TestClient, headers, query: str = "") -> set[str]:
    resp = client.get(f"{API}/orders/{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    return {o["order_number"] for o in resp.json()["data"]["orders"]}


class TestList:
    def test_cashier_lists_only_their_own_orders(self, client: TestClient, world, orders, as_):
        assert _listed(client, as_("pos_a", "A")) == {"SC-A1"}

    def test_cashier_asking_for_someone_elses_orders_is_403(self, client: TestClient, world, orders, as_):
        resp = client.get(f"{API}/orders/?user_id={world.users['pos_a2']}", headers=as_("pos_a", "A"))
        assert resp.status_code == 403
        assert _listed(client, as_("pos_a", "A"), f"?user_id={world.users['pos_a']}") == {"SC-A1"}

    def test_branch_manager_lists_the_whole_branch_and_may_filter(self, client: TestClient, world, orders, as_):
        assert _listed(client, as_("pos_a", "A")) == {"SC-A1"}
        assert _listed(client, as_("ba_a", "A")) == {"SC-A1", "SC-A2"}
        assert _listed(client, as_("ba_a", "A"), f"?user_id={world.users['pos_a2']}") == {"SC-A2"}

    def test_manager_at_a_is_a_cashier_at_b(self, client: TestClient, world, orders, as_):
        assert _listed(client, as_("mixed", "B")) == set()
        assert _listed(client, as_("mixed", "A")) == {"SC-A1", "SC-A2"}


@pytest.mark.parametrize("path", ["/orders/{o}", "/orders/SC-A2", "/orders/{o}/receipt", "/orders/track/TRK-A2"])
def test_cashier_cannot_open_another_cashiers_order_of_the_same_branch(
    client: TestClient, world, orders, as_, path
):
    url = API + path.format(o=orders["a2"])
    assert client.get(url, headers=as_("pos_a", "A")).status_code == 404
    assert client.get(url, headers=as_("pos_a2", "A")).status_code == 200
    assert client.get(url, headers=as_("ba_a", "A")).status_code == 200

"""An order is reached only by someone holding the permission at its branch (Phase 35c ②)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.scope_fixtures import API, as_, orders, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

#: (method, path, body); {o} is the order id, {n} its order number, {t} its tracking number.
ROUTES = [
    ("GET", "/orders/{o}", None),
    ("GET", "/orders/{n}", None),
    ("GET", "/orders/{o}/receipt", None),
    ("GET", "/orders/track/{t}", None),
    ("PUT", "/orders/{o}/status", {"status": "preparing"}),
    ("PUT", "/orders/{o}/tracking", {"tracking_number": "NEW-1"}),
    ("POST", "/orders/{o}/tracking-token", None),
    ("POST", "/orders/{o}/cancel", {"reason": "x"}),
    ("PUT", "/orders/{o}/complete", None),
    ("POST", "/orders/{o}/checkout", {"payments": [{"payment_method": "cash", "amount": "100"}]}),
]


def _call(client: TestClient, method: str, path: str, body, name: str, orders, headers):
    url = API + path.format(o=orders[name], n=f"SC-{name.upper()}", t=f"TRK-{name.upper()}")
    return client.request(method, url, json=body, headers=headers)


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_an_order_of_another_branch_is_404(client: TestClient, world, orders, as_, method, path, body):
    resp = _call(client, method, path, body, "b1", orders, as_("ba_a", "A"))
    assert resp.status_code == 404
    # The header does not widen it: ba_a has no role at B.
    assert _call(client, method, path, body, "b1", orders, as_("ba_a")).status_code == 404

    resp = _call(client, method, path, body, "a1", orders, as_("ba_a", "A"))
    assert resp.status_code not in (403, 404), resp.text


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_superadmin_and_organization_wide_manager_reach_both_branches(
    client: TestClient, world, orders, as_, method, path, body
):
    # Missing the permission everywhere is 403; holding it at A only, 404.
    assert _call(client, method, path, body, "b1", orders, as_("pos_a", "A")).status_code in (403, 404)
    for who in ("sa", "orgmgr"):
        resp = _call(client, method, path, body, "b1", orders, as_(who))
        assert resp.status_code not in (403, 404), (who, resp.text)


def test_manager_at_a_cashier_at_b_cannot_cancel_at_b(client: TestClient, world, orders, as_):
    # orders.cancel: Manager only; mixed is Cashier at B.
    assert client.post(f"{API}/orders/{orders['b1']}/cancel", json={}, headers=as_("mixed", "B")).status_code == 404
    assert client.get(f"{API}/orders/{orders['b1']}", headers=as_("mixed", "B")).status_code != 404
    resp = client.post(f"{API}/orders/{orders['a1']}/cancel", json={}, headers=as_("mixed", "A"))
    assert resp.status_code == 200

"""A route that works at a branch, called without X-Branch-Id (Phase 42, item 2).

400 BRANCH_REQUIRED with a Thai message, apart from 401 (the login is fine),
403 FORBIDDEN (the permission is not held, or not at the branch sent) and 404
(a record of another branch). v0.1.15 answered 401 on some routes and 403
"Missing required permission" on the others.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.shared.exceptions import BRANCH_REQUIRED_DETAIL
from tests.integration.conftest import idem
from tests.integration.money_fixtures import shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, orders, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _branch_required(resp) -> None:
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert (body["code"], body["detail"]) == ("BRANCH_REQUIRED", BRANCH_REQUIRED_DETAIL)
    assert "X-Branch-Id" in body["detail"] and body["request_id"]


@pytest.mark.parametrize("path", ["/orders/", "/customers/", "/catalog/products", "/returns/",
                                  "/orders/station/kitchen"])
def test_a_branch_user_without_the_header_is_400(client: TestClient, world, as_, path):
    who = "kitchen_a" if "station" in path else "pos_a"
    _branch_required(client.get(API + path, headers=as_(who)))
    assert client.get(API + path, headers=as_(who, "A")).status_code == 200


def test_creating_an_order_without_the_header_is_400(client: TestClient, world, shop, as_):
    resp = client.post(f"{API}/orders/", headers=idem(as_("pos_a")),
                       json={"branch_id": world.A, "items": [{"product_id": shop.wine, "quantity": 1}]})
    _branch_required(resp)


def test_a_permission_held_nowhere_is_still_403(client: TestClient, world, as_):
    # A cashier has no slip_verification.* and no registers.create anywhere.
    resp = client.post(f"{API}/registers/", headers=as_("pos_a"), json={"branch_id": world.A, "name": "x"})
    assert (resp.status_code, resp.json()["code"]) == (403, "FORBIDDEN")
    resp = client.post(f"{API}/registers/", headers=as_("pos_a", "A"), json={"branch_id": world.A, "name": "x"})
    assert (resp.status_code, resp.json()["code"]) == (403, "FORBIDDEN")


def test_a_branch_without_a_role_is_still_403(client: TestClient, world, as_):
    resp = client.get(f"{API}/orders/", headers=as_("pos_a", "B"))
    assert (resp.status_code, resp.json()["code"]) == (403, "FORBIDDEN")


def test_another_branchs_record_is_still_404(client: TestClient, world, orders, as_):
    resp = client.get(f"{API}/orders/{orders['b1']}", headers=as_("pos_a", "A"))
    assert (resp.status_code, resp.json()["code"]) == (404, "NOT_FOUND")


def test_an_organization_wide_role_needs_no_header(client: TestClient, world, as_):
    assert client.get(f"{API}/customers/", headers=as_("orgmgr")).status_code == 200


def test_no_token_is_still_401(client: TestClient, world):
    resp = client.get(f"{API}/orders/")
    assert (resp.status_code, resp.json()["code"]) == (401, "UNAUTHORIZED")

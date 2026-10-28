"""Permissions that existed but guarded nothing (Phase 40, item 6).

- GET /roles/, /roles/{id}, /roles/permissions/all need roles.read (they
  needed only a login: a kitchen account read every role and permission).
  The Branch Admin, who assigns roles, holds it at their branch.
- GET /api/admin/promotions (new): the admin list, inactive and ended
  promotions too, needs promotions.read; GET /api/promotions stays public.
- coupons.update guards nothing: there is no PUT /coupons/{id} (405).
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.shared.clock import store_now
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def test_roles_need_roles_read(client: TestClient, world, as_):
    manager = world.roles["Manager"]
    for path in ("/roles/", f"/roles/{manager}", "/roles/permissions/all"):
        for who in ("pos_a", "kitchen_a", "bar_a"):
            assert client.get(API + path, headers=as_(who, "A")).status_code == 403, (path, who)
        assert client.get(API + path).status_code == 401
        for who in ("ba_a", "orgmgr", "sa"):
            assert client.get(API + path, headers=as_(who, "A")).status_code == 200, (path, who)
    role = client.get(f"{API}/roles/{manager}", headers=as_("ba_a", "A")).json()["data"]
    assert role["name"] == "Manager" and "roles.read" in {p["code"] for p in role["permissions"]}
    codes = {p["code"] for p in client.get(f"{API}/roles/permissions/all", headers=as_("ba_a", "A")).json()["data"]}
    assert {"roles.read", "promotions.read", "orders.read"} <= codes
    assert client.get(f"{API}/roles/999999", headers=as_("sa", "A")).status_code == 404


def _promotion(pid: str, **extra) -> dict:
    return {"id": pid, "title": pid, "description": "P40", "imageUrl": "/p.png", **extra}


def test_the_admin_promotion_list(client: TestClient, world, as_):
    ended = (store_now() - timedelta(days=1)).replace(tzinfo=None).isoformat()
    for body in (_promotion("p40-live"), _promotion("p40-off", isActive=False), _promotion("p40-ended", endsAt=ended)):
        assert client.post("/api/admin/promotions", json=body, headers=as_("sa", "A")).status_code == 201

    public = {p["id"] for p in client.get("/api/promotions").json()["promotions"]}
    assert "p40-live" in public and not {"p40-off", "p40-ended"} & public

    for who in ("ba_a", "sa"):
        resp = client.get("/api/admin/promotions", headers=as_(who, "A"))
        assert resp.status_code == 200, (who, resp.text)
        assert {"p40-live", "p40-off", "p40-ended"} <= {p["id"] for p in resp.json()["promotions"]}
    for who in ("pos_a", "kitchen_a"):
        assert client.get("/api/admin/promotions", headers=as_(who, "A")).status_code == 403
    assert client.get("/api/admin/promotions").status_code == 401


def test_there_is_no_coupon_update_route(client: TestClient, world, as_):
    assert client.put(f"{API}/coupons/1", json={}, headers=as_("sa", "A")).status_code == 405

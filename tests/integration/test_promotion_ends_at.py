"""A promotion ends (Phase 38c, left over from 36b).

promotions.ends_at: GET /api/promotions leaves out an ended promotion; a time
sent without an offset is store time (STORE_TIMEZONE).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.shared.clock import store_now, store_zone
from tests.integration.scope_fixtures import as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _promotion(pid: str, **extra) -> dict:
    return {"id": pid, "title": pid, "description": "E2E", "imageUrl": "/p.png", **extra}


def _listed(client: TestClient) -> set[str]:
    resp = client.get("/api/promotions")
    assert resp.status_code == 200, resp.text
    return {p["id"] for p in resp.json()["promotions"]}


def test_an_ended_promotion_is_not_listed(client: TestClient, world, as_):
    wall = store_now().replace(tzinfo=None, microsecond=0)
    for pid, ends in (("running", wall + timedelta(hours=1)), ("ended", wall - timedelta(minutes=1)),
                      ("open", None)):
        body = _promotion(pid, endsAt=ends.isoformat() if ends else None)
        resp = client.post("/api/admin/promotions", json=body, headers=as_("sa", "A"))
        assert resp.status_code == 201, resp.text
    assert _listed(client) == {"running", "open"}

    resp = client.put("/api/admin/promotions", json={"id": "ended", "endsAt": None}, headers=as_("sa", "A"))
    assert resp.status_code == 200, resp.text
    assert _listed(client) == {"running", "open", "ended"}


def test_a_time_without_an_offset_is_store_time(client: TestClient, world, as_):
    resp = client.post("/api/admin/promotions", json=_promotion("newyear", endsAt="2030-01-01T00:00:00"),
                       headers=as_("sa", "A"))
    assert resp.status_code == 201, resp.text
    ends = datetime.fromisoformat(resp.json()["promotion"]["endsAt"])
    assert ends == datetime(2030, 1, 1, tzinfo=store_zone())

    resp = client.post("/api/admin/promotions", json=_promotion("utc", endsAt="2030-01-01T00:00:00+00:00"),
                       headers=as_("sa", "A"))
    assert datetime.fromisoformat(resp.json()["promotion"]["endsAt"]) == datetime.fromisoformat(
        "2030-01-01T00:00:00+00:00")

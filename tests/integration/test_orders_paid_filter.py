"""GET /orders/ filters by when an order was paid (Phase 38b, left over from 38a).

``date_field=paid_at`` compares date_from/date_to with paid_at (the day the
reports count the sale); the default stays created_at.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.conftest import idem
from tests.integration.money_fixtures import checkout, new_order, shop  # noqa: F401  (fixtures)
from tests.integration.scope_fixtures import API, as_, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _listed(client: TestClient, as_, **params) -> set[int]:
    resp = client.get(f"{API}/orders/", headers=as_("ba_a", "A"), params=params)
    assert resp.status_code == 200, resp.text
    return {o["id"] for o in resp.json()["data"]["orders"]}


def test_paid_at_finds_an_order_made_earlier_and_paid_now(client: TestClient, session: Session, world, shop, as_):
    from app.db.models import Order

    old = new_order(client, idem(as_("ba_a", "A")), world.A, [(shop.wine, 1)])
    session.get(Order, old["id"]).created_at = datetime.now(timezone.utc) - timedelta(days=2)
    session.commit()
    assert checkout(client, idem(as_("ba_a", "A")), old["id"], ("cash", "350.00")).status_code == 200
    unpaid = new_order(client, idem(as_("ba_a", "A")), world.A, [(shop.wine, 1)])

    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert _listed(client, as_, date_from=since) == {unpaid["id"]}
    assert _listed(client, as_, date_from=since, date_field="created_at") == {unpaid["id"]}
    assert _listed(client, as_, date_from=since, date_field="paid_at") == {old["id"]}
    two_days = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    assert _listed(client, as_, date_from=two_days, date_to=since, date_field="paid_at") == set()


def test_another_date_field_is_422(client: TestClient, as_, world):
    resp = client.get(f"{API}/orders/", headers=as_("ba_a", "A"), params={"date_field": "updated_at"})
    assert resp.status_code == 422

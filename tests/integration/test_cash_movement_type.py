"""A cash movement is cash_in or cash_out, what the database allows; anything else is 422, not 500 (Phase 35d D)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import ShiftCashMovement
from tests.integration.scope_fixtures import API, as_, shifts, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _move(client: TestClient, headers, shift_id: int, movement_type) -> int:
    body = {"movement_type": movement_type, "amount": "10.00", "reason": "test"}
    return client.post(f"{API}/shifts/{shift_id}/cash-movements", json=body, headers=headers).status_code


@pytest.mark.parametrize("movement_type", ["drop", "pickup", "opening", "closing", "CASH_IN", "", None, 1])
def test_other_movement_types_are_422(client: TestClient, session, world, shifts, as_, movement_type):
    assert _move(client, as_("ba_a", "A"), shifts["a1"], movement_type) == 422
    count = session.scalar(select(func.count()).select_from(ShiftCashMovement).where(
        ShiftCashMovement.shift_id == shifts["a1"]))
    assert count == 0


@pytest.mark.parametrize("movement_type", ["cash_in", "cash_out"])
def test_cash_in_and_cash_out_are_recorded(client: TestClient, world, shifts, as_, movement_type):
    assert _move(client, as_("ba_a", "A"), shifts["a1"], movement_type) == 201

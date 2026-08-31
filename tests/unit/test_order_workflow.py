from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domains.orders.service import OrderService
from app.shared.exceptions import BadRequestException, InvalidOrderStateException, NotFoundException


def _make_order(status="pending", grand_total=Decimal("0"), amount_paid=Decimal("0")):
    order = MagicMock()
    order.status = status
    order.grand_total = grand_total
    order.amount_paid = amount_paid
    order.completed_at = None
    return order


@pytest.fixture()
def mock_repo(monkeypatch):
    from app.domains.orders import service as svc

    order_holder = {"order": _make_order()}

    class Stub:
        @staticmethod
        def get_org_order(db, org, oid):
            return order_holder["order"]

        get_product = staticmethod(lambda db, pid: None)

    monkeypatch.setattr(svc, "OrderRepository", Stub)

    return order_holder


class TestUpdateStatus:
    @pytest.mark.parametrize(
        "start,target",
        [
            ("pending", "confirmed"),
            ("confirmed", "preparing"),
            ("confirmed", "ready"),
            ("preparing", "ready"),
            ("ready", "completed"),
        ],
    )
    def test_valid_transitions(self, mock_repo, start, target):
        order = mock_repo["order"]
        order.status = start
        order.amount_paid = Decimal("100")
        order.grand_total = Decimal("80")
        fake_db = MagicMock()
        result = OrderService.update_status(fake_db, 1, 1, target, user_id=1)
        assert result.status == target
        if target == "completed":
            assert result.completed_at is not None

    @pytest.mark.parametrize(
        "start,target",
        [
            ("pending", "completed"),
            ("pending", "preparing"),
            ("pending", "ready"),
            ("confirmed", "confirmed"),
            ("preparing", "confirmed"),
            ("ready", "preparing"),
            ("completed", "ready"),
        ],
    )
    def test_invalid_transitions_raise(self, mock_repo, start, target):
        order = mock_repo["order"]
        order.status = start
        with pytest.raises(InvalidOrderStateException):
            OrderService.update_status(None, 1, 1, target)

    def test_cancel_rejected_via_update_status(self, mock_repo):
        with pytest.raises(BadRequestException):
            OrderService.update_status(None, 1, 1, "cancelled")

    def test_invalid_status_value_rejected(self, mock_repo):
        with pytest.raises(BadRequestException):
            OrderService.update_status(None, 1, 1, "bogus_status")

    def test_missing_order_raises_not_found(self, monkeypatch):
        from app.domains.orders import service as svc

        class Stub:
            get_org_order = MagicMock(return_value=None)

        monkeypatch.setattr(svc, "OrderRepository", Stub)
        with pytest.raises(NotFoundException):
            OrderService.update_status(None, 1, 1, "confirmed")

    def test_complete_requires_paid(self, mock_repo):
        order = mock_repo["order"]
        order.status = "ready"
        order.amount_paid = Decimal("50")
        order.grand_total = Decimal("80")
        with pytest.raises(BadRequestException):
            OrderService.update_status(None, 1, 1, "completed")


class TestCancelRules:
    @pytest.mark.parametrize("start", ["pending", "confirmed", "preparing"])
    def test_cancellable_statuses(self, start):
        assert start in OrderService.CANCELLABLE_STATUSES

    @pytest.mark.parametrize("start", ["ready", "completed", "cancelled"])
    def test_non_cancellable_statuses(self, start):
        assert start not in OrderService.CANCELLABLE_STATUSES

    def test_valid_transition_table_is_complete(self):
        for status in ("pending", "confirmed", "preparing", "ready", "completed", "cancelled"):
            assert status in OrderService.VALID_TRANSITIONS

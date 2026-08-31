from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domains.orders.service import OrderService
from app.shared.exceptions import NotFoundException


def _make_order(order_id=7):
    order = MagicMock()
    order.id = order_id
    order.organization_id = 1
    order.branch_id = 2
    order.order_number = "MBR-20260829-0001"
    order.status = "completed"
    order.created_at = datetime.now(timezone.utc)
    order.completed_at = datetime.now(timezone.utc)
    order.register_id = None
    order.shift_id = None
    order.customer_id = None
    order.subtotal = Decimal("100")
    order.discount_amount = Decimal("0")
    order.tax_amount = Decimal("0")
    order.grand_total = Decimal("100")
    order.amount_paid = Decimal("100")
    order.change_amount = Decimal("0")
    order.loyalty_points_earned = 0
    order.loyalty_points_redeemed = 0
    return order


@pytest.fixture()
def mock_repo(monkeypatch):
    from app.domains.orders import service as svc

    orders_by_number = {}

    class Stub:
        @staticmethod
        def get_org_order(db, org, oid):
            return _make_order(oid) if oid == 7 else None

        @staticmethod
        def get_org_order_by_number(db, org, number):
            return orders_by_number.get(number)

    monkeypatch.setattr(svc, "OrderRepository", Stub)
    return {"orders_by_number": orders_by_number}


class TestGetOrderByReference:
    def test_numeric_reference_uses_id(self, mock_repo):
        order = OrderService.get_order_by_reference(None, 1, "7")
        assert order.id == 7

    def test_numeric_reference_missing_raises(self, mock_repo):
        with pytest.raises(NotFoundException):
            OrderService.get_order_by_reference(None, 1, "999")

    def test_alphanumeric_reference_uses_number(self, mock_repo):
        order = _make_order(3)
        mock_repo["orders_by_number"]["ORD-0001"] = order
        result = OrderService.get_order_by_reference(None, 1, "ORD-0001")
        assert result.id == 3

    def test_alphanumeric_missing_raises(self, mock_repo):
        with pytest.raises(NotFoundException):
            OrderService.get_order_by_reference(None, 1, "NOPE-123")

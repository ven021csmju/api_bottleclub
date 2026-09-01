from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domains.orders.service import OrderService
from app.shared.exceptions import (
    BadRequestException,
    InvalidOrderStateException,
    NotFoundException,
)


def _make_order(status="pending", grand_total=Decimal("1000")):
    order = MagicMock()
    order.id = 7
    order.status = status
    order.customer_id = 1
    order.grand_total = grand_total
    order.amount_paid = Decimal("0")
    order.change_amount = Decimal("0")
    order.loyalty_points_redeemed = 0
    order.loyalty_points_earned = 0
    order.completed_at = None
    return order


def _make_customer(balance=500):
    customer = MagicMock()
    customer.id = 1
    customer.loyalty_points_balance = balance
    return customer


@pytest.fixture()
def svc_modules(monkeypatch):
    from app.domains.orders import service as svc

    state = {"anchor": _make_order(), "txn": []}

    class OrderRepoStub:
        @staticmethod
        def get_org_order(db, org, oid):
            return state["anchor"]

    class LoyaltyRepoStub:
        @staticmethod
        def find_org_customer(db, org, cid):
            return state.get("customer")

        @staticmethod
        def add_transaction(db, txn):
            state["txn"].append(txn)

    class PaymentRepoStub:
        @staticmethod
        def add_payment(db, payment):
            state.setdefault("payments", []).append(payment)

    monkeypatch.setattr(svc, "OrderRepository", OrderRepoStub)
    monkeypatch.setattr(svc, "LoyaltyRepository", LoyaltyRepoStub)
    monkeypatch.setattr(svc, "PaymentRepository", PaymentRepoStub)
    return state


class TestCheckout:
    def test_settles_order_and_earns_points(self, svc_modules):
        svc_modules["customer"] = _make_customer(balance=100)
        order = svc_modules["anchor"]
        order.status = "pending"

        result = OrderService.checkout_order(
            MagicMock(), 1, order.id, user_id=9,
            data={
                "payments": [{"payment_method": "cash", "amount": "1000"}],
                "redeem_points": 0,
                "earn_points": True,
            },
        )

        assert result.status == "paid"
        assert result.amount_paid == Decimal("1000")
        assert result.change_amount == Decimal("0")
        # 1 point per baht on the 1000 spend
        assert result.loyalty_points_earned == 1000
        assert svc_modules["customer"].loyalty_points_balance == 1100

    def test_redeem_points_reduce_due(self, svc_modules):
        svc_modules["customer"] = _make_customer(balance=500)
        order = svc_modules["anchor"]  # grand_total 1000
        order.status = "ready"

        result = OrderService.checkout_order(
            MagicMock(), 1, order.id, user_id=9,
            data={
                "payments": [{"payment_method": "qr_code", "amount": "900"}],
                "redeem_points": 100,
                "earn_points": True,
            },
        )

        assert result.loyalty_points_redeemed == 100
        assert result.amount_paid == Decimal("900")
        assert result.change_amount == Decimal("0")
        # customer: 500 - 100 (redeem) then earn on 900 net
        assert result.loyalty_points_earned == 900
        assert svc_modules["customer"].loyalty_points_balance == 1300

    def test_insufficient_payment_rejected_and_not_committed(self, svc_modules):
        svc_modules["customer"] = _make_customer(balance=100)
        order = svc_modules["anchor"]
        order.status = "pending"
        db = MagicMock()

        with pytest.raises(BadRequestException):
            OrderService.checkout_order(
                db, 1, order.id, user_id=9,
                data={"payments": [{"payment_method": "cash", "amount": "500"}]},
            )
        # atomicity: nothing is committed when settlement fails
        db.commit.assert_not_called()

    def test_redeem_without_customer_rejected(self, svc_modules):
        order = svc_modules["anchor"]
        order.customer_id = None
        with pytest.raises(BadRequestException):
            OrderService.checkout_order(
                MagicMock(), 1, order.id, user_id=9,
                data={
                    "payments": [{"payment_method": "cash", "amount": "1000"}],
                    "redeem_points": 10,
                },
            )

    def test_insufficient_points_rejected(self, svc_modules):
        svc_modules["customer"] = _make_customer(balance=50)
        order = svc_modules["anchor"]
        with pytest.raises(BadRequestException):
            OrderService.checkout_order(
                MagicMock(), 1, order.id, user_id=9,
                data={
                    "payments": [{"payment_method": "cash", "amount": "1000"}],
                    "redeem_points": 100,
                },
            )

    def test_idempotent_returns_settled_order_without_charging_again(self, svc_modules):
        order = svc_modules["anchor"]
        order.status = "paid"
        before = svc_modules.get("payments", [])

        result = OrderService.checkout_order(
            MagicMock(), 1, order.id, user_id=9,
            data={
                "payments": [{"payment_method": "cash", "amount": "1000"}],
                "idempotency_key": "retry-key",
            },
        )

        assert result is order
        assert svc_modules.get("payments", []) == before  # no new payments

    def test_non_checkoutable_status_rejected(self, svc_modules):
        order = svc_modules["anchor"]
        order.status = "completed"
        with pytest.raises(InvalidOrderStateException):
            OrderService.checkout_order(
                MagicMock(), 1, order.id, user_id=9,
                data={"payments": [{"payment_method": "cash", "amount": "1000"}]},
            )

    def test_missing_order_raises_not_found(self, monkeypatch):
        from app.domains.orders import service as svc

        class Stub:
            get_org_order = MagicMock(return_value=None)
            get_stations_for_products = staticmethod(lambda *a, **k: {})

        monkeypatch.setattr(svc, "OrderRepository", Stub)
        with pytest.raises(NotFoundException):
            OrderService.checkout_order(
                MagicMock(), 1, 999, user_id=9,
                data={"payments": [{"payment_method": "cash", "amount": "1000"}]},
            )

    def test_no_payments_rejected_and_not_committed(self, svc_modules):
        svc_modules["customer"] = _make_customer(balance=100)
        order = svc_modules["anchor"]
        order.status = "pending"
        db = MagicMock()

        with pytest.raises(BadRequestException):
            OrderService.checkout_order(
                db, 1, order.id, user_id=9, data={"payments": []}
            )
        db.commit.assert_not_called()
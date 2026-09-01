from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domains.returns.service import ReturnService
from app.shared.exceptions import NotFoundException


def _make_order():
    order = MagicMock()
    order.id = 11
    return order


def _make_order_item(oid=5):
    item = MagicMock()
    item.id = oid
    item.product_id = 100
    item.quantity = 4
    item.unit_price = Decimal("50")
    return item


@pytest.fixture()
def svc_module(monkeypatch):
    from app.domains.returns import service as svc

    state = {
        "order": _make_order(),
        "order_items": [_make_order_item()],
        "refund": None,
        "return_id": 7,
    }

    class StubRepo:
        @staticmethod
        def get_org_order(db, org, oid):
            return state["order"]

        @staticmethod
        def add_return(db, ret):
            ret.id = state["return_id"]
            return ret

        @staticmethod
        def list_order_items(db, order_id):
            return state["order_items"]

        @staticmethod
        def add_return_item(db, item):
            item.id = 1

        @staticmethod
        def get_inventory(db, branch_id, product_id):
            return None

        @staticmethod
        def add_inventory(db, inv):
            pass

        @staticmethod
        def add_stock_movement(db, movement):
            pass

        @staticmethod
        def add_refund(db, refund):
            refund.id = 99
            state["refund"] = refund
            return refund

    monkeypatch.setattr(svc, "ReturnRepository", StubRepo)
    monkeypatch.setattr(
        svc, "generate_return_number", staticmethod(lambda db: "RET-20260830-0001")
    )
    monkeypatch.setattr(
        svc, "generate_refund_number", staticmethod(lambda db: "REF-20260830-0001")
    )
    return state


class TestCreateReturn:
    def test_creates_refund_with_valid_status_and_no_bad_attr(self, svc_module):
        result = ReturnService.create_return(
            db=MagicMock(),
            org_id=1,
            branch_id=2,
            user_id=3,
            data={
                "order_id": 11,
                "reason": "Damaged",
                "items": [
                    {
                        "order_item_id": 5,
                        "product_id": 100,
                        "quantity": 2,
                        "restock": True,
                        "return_reason": "defective",
                    }
                ],
            },
        )

        # The return is linked to the created refund.
        assert result.id == svc_module["return_id"]
        assert result.refund_id == 99

        refund = svc_module["refund"]
        assert refund is not None
        # Status must satisfy the refunds DB check constraint
        # ('pending', 'completed', 'failed') -- NOT 'processed'.
        assert refund.status in ("pending", "completed", "failed")
        assert refund.refund_amount == Decimal("100")
        assert refund.refund_method == "original"
        # Regression guard: Refund has no 'return_id' attribute, so constructing
        # one with return_id=... used to break. Ensure it isn't set.
        assert not hasattr(refund, "return_id")

    def test_missing_order_raises(self, svc_module):
        svc_module["order"] = None
        with pytest.raises(NotFoundException):
            ReturnService.create_return(
                db=MagicMock(),
                org_id=1,
                branch_id=2,
                user_id=3,
                data={
                    "order_id": 999,
                    "reason": "x",
                    "items": [],
                },
            )

    def test_total_refund_is_zero_without_restock_no_refund_read(self, svc_module):
        # with restock False and quantity, refund amount still computed
        ReturnService.create_return(
            db=MagicMock(),
            org_id=1,
            branch_id=2,
            user_id=3,
            data={
                "order_id": 11,
                "reason": "x",
                "items": [
                    {
                        "order_item_id": 5,
                        "product_id": 100,
                        "quantity": 1,
                        "restock": False,
                    }
                ],
            },
        )
        refund = svc_module["refund"]
        assert refund.refund_amount == Decimal("50")
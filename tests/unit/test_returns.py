from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domains.returns.service import ReturnService
from app.shared.exceptions import BadRequestException, NotFoundException


def _make_order(status="paid"):
    order = MagicMock()
    order.id = 11
    order.status = status
    return order


def _make_order_item(oid=5):
    item = MagicMock()
    item.id = oid
    item.product_id = 100
    item.quantity = 4
    item.unit_price = Decimal("50")
    item.line_total = Decimal("200")
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
        def returned_quantities(db, order_id):
            return state.get("returned", {})

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
    # The order took 160 for its 200 of lines (a discount of 20%).
    monkeypatch.setattr(svc, "paid_net", lambda db, order_id: state.get("paid", Decimal("160")))
    monkeypatch.setattr(
        svc, "generate_return_number", staticmethod(lambda db: "RET-20260830-0001")
    )
    monkeypatch.setattr(
        svc, "generate_refund_number", staticmethod(lambda db: "REF-20260830-0001")
    )
    return state


def _create(quantity=2, restock=True):
    return ReturnService.create_return(
        db=MagicMock(),
        org_id=1,
        branch_id=2,
        user_id=3,
        data={
            "order_id": 11,
            "reason": "Damaged",
            "items": [{"order_item_id": 5, "product_id": 100, "quantity": quantity,
                       "restock": restock, "return_reason": "defective"}],
        },
    )


class TestCreateReturn:
    """Creating a return only records it (Phase 38a): the refund and the
    restock happen when it is processed (tests/integration/test_returns_money.py)."""

    def test_is_pending_and_refunds_nothing_yet(self, svc_module):
        result = _create()
        assert result.id == svc_module["return_id"]
        assert result.status == "pending"
        assert result.refund_id is None
        assert svc_module["refund"] is None

    def test_unit_refund_is_the_share_of_what_was_paid(self, svc_module):
        added = []
        from app.domains.returns import service as svc
        original = svc.ReturnRepository.add_return_item
        svc.ReturnRepository.add_return_item = staticmethod(lambda db, item: added.append(item))
        try:
            _create()
        finally:
            svc.ReturnRepository.add_return_item = original
        # 200 / 4 per unit, scaled by 160 / 200.
        assert [i.unit_price for i in added] == [Decimal("40.00")]

    def test_missing_order_raises(self, svc_module):
        svc_module["order"] = None
        with pytest.raises(NotFoundException):
            ReturnService.create_return(
                db=MagicMock(), org_id=1, branch_id=2, user_id=3,
                data={"order_id": 999, "reason": "x", "items": []},
            )

    @pytest.mark.parametrize("status", ["pending", "cancelled", "held"])
    def test_an_unpaid_order_cannot_be_returned(self, svc_module, status):
        svc_module["order"] = _make_order(status)
        with pytest.raises(BadRequestException) as exc:
            _create()
        assert exc.value.code == "ORDER_NOT_PAID"

    def test_more_than_is_left_to_return_is_refused(self, svc_module):
        svc_module["returned"] = {5: 3}
        with pytest.raises(BadRequestException) as exc:
            _create(quantity=2)
        assert exc.value.code == "RETURN_QUANTITY_EXCEEDED"

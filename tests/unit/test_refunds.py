from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domains.refunds.service import RefundService
from app.shared.exceptions import BadRequestException, NotFoundException


def _make_order(grand_total=Decimal("100")):
    order = MagicMock()
    order.id = 5
    order.organization_id = 1
    order.grand_total = grand_total
    return order


@pytest.fixture()
def svc_module(monkeypatch):
    from app.domains.refunds import service as svc

    holder = {"order": _make_order(), "refunds": []}

    class StubRepo:
        @staticmethod
        def get_org_order(db, org, oid):
            if holder["order"] is None:
                return None
            return holder["order"]

        @staticmethod
        def add_refund(db, refund):
            refund.id = 99
            holder["refunds"].append(refund)
            return refund

    monkeypatch.setattr(svc, "RefundRepository", StubRepo)
    monkeypatch.setattr(
        svc, "generate_refund_number", staticmethod(lambda db: "REF-20260829-0001")
    )
    monkeypatch.setattr(svc, "log_audit", MagicMock())
    return holder


def _ctx():
    return MagicMock()


class TestCreateRefund:
    def test_create_ok(self, svc_module):
        order = svc_module["order"]
        refund = RefundService.create_refund(
            db=MagicMock(),
            org_id=1,
            user_id=3,
            audit=_ctx(),
            data={
                "order_id": 5,
                "refund_amount": Decimal("40"),
                "refund_method": "cash",
                "reason": "Damaged",
                "external_reference": None,
            },
        )
        assert refund.id == 99
        assert refund.order_id == order.id
        assert refund.refund_number == "REF-20260829-0001"
        assert refund.refund_amount == Decimal("40")
        assert refund.status == "pending"
        assert refund.processed_by == 3
        assert refund.reason == "Damaged"

    def test_create_missing_order_raises(self, svc_module):
        svc_module["order"] = None
        from app.domains.refunds import service as svc

        with pytest.raises(NotFoundException):
            RefundService.create_refund(
                db=MagicMock(),
                org_id=1,
                user_id=3,
                audit=_ctx(),
                data={
                    "order_id": 999,
                    "refund_amount": Decimal("10"),
                    "refund_method": "cash",
                },
            )

    def test_create_amount_exceeds_total_raises(self, svc_module):
        with pytest.raises(BadRequestException):
            RefundService.create_refund(
                db=MagicMock(),
                org_id=1,
                user_id=3,
                audit=_ctx(),
                data={
                    "order_id": 5,
                    "refund_amount": Decimal("999"),
                    "refund_method": "cash",
                },
            )

    def test_create_logs_audit(self, svc_module):
        from app.domains.refunds import service as svc

        ctx = _ctx()
        RefundService.create_refund(
            db=MagicMock(),
            org_id=1,
            user_id=3,
            audit=ctx,
            data={
                "order_id": 5,
                "refund_amount": Decimal("20"),
                "refund_method": "card",
            },
        )
        svc.log_audit.assert_called_once()
        assert svc.log_audit.call_args.kwargs["action"] == "REFUND.CREATE"
        assert svc.log_audit.call_args.kwargs["ctx"] is ctx

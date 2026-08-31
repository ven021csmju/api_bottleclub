from datetime import date
from types import SimpleNamespace

import pytest

from app.domains.reports.service import ReportService


@pytest.fixture()
def patched_repo(monkeypatch):
    from app.domains.reports import service as service_module

    class StubRepo:
        calls = {}

        @staticmethod
        def inventory_report(db, organization_id, branch_id=None, category_id=None):
            return [
                SimpleNamespace(
                    product_id=1,
                    product_name="Beer",
                    sku="B1",
                    category="Drink",
                    on_hand=5,
                    reserved=1,
                    cost_price=5.0,
                ),
                SimpleNamespace(
                    product_id=2,
                    product_name="Cola",
                    sku="C1",
                    category=None,
                    on_hand=50,
                    reserved=0,
                    cost_price=1.5,
                ),
            ]

        @staticmethod
        def financial_report(db, organization_id, date_from, date_to, branch_id=None):
            return [
                SimpleNamespace(
                    date=date(2026, 1, 2),
                    gross_sales=100.0,
                    discounts=10.0,
                    tax=7.0,
                ),
                SimpleNamespace(
                    date=date(2026, 1, 3),
                    gross_sales=50.0,
                    discounts=5.0,
                    tax=3.5,
                ),
            ]

        @staticmethod
        def refund_summary(db, organization_id, date_from, date_to, branch_id=None):
            return [SimpleNamespace(date=date(2026, 1, 2), refunds=4.0)]

        @staticmethod
        def payment_method_summary(db, organization_id, date_from, date_to, branch_id=None):
            return [
                SimpleNamespace(payment_method="cash", amount=140.0),
                SimpleNamespace(payment_method="card", amount=10.0),
            ]

        @staticmethod
        def loyalty_report(db, organization_id, date_from, date_to):
            return [
                SimpleNamespace(
                    customer_id=1,
                    customer_name="Alice Foo",
                    points_earned=10,
                    points_redeemed=2,
                    points_balance=8,
                ),
                SimpleNamespace(
                    customer_id=2,
                    customer_name="Bob Bar",
                    points_earned=5,
                    points_redeemed=0,
                    points_balance=5,
                ),
            ]

        @staticmethod
        def loyalty_order_counts(db, organization_id, date_from, date_to):
            return [SimpleNamespace(customer_id=1, order_count=3)]

        @staticmethod
        def sales_totals(db, organization_id, date_from, date_to, branch_id=None):
            return SimpleNamespace(total_sales=150.0, total_orders=4)

    monkeypatch.setattr(
        service_module,
        "ReportRepository",
        StubRepo,
    )
    return StubRepo


class TestInventoryReport:
    def test_shape_and_totals(self, patched_repo):
        result = ReportService.get_inventory_report(None, 1)
        assert result["total_products"] == 2
        assert result["total_units"] == 55
        assert result["total_stock_value"] == 100.0
        assert result["low_stock_count"] == 1
        assert result["items"][0]["available"] == 4
        assert result["items"][1]["low_stock"] is False


class TestFinancialReport:
    def test_totals_and_daily(self, patched_repo):
        result = ReportService.get_financial_report(None, 1, date(2026, 1, 1), date(2026, 1, 31))
        assert result["gross_sales"] == 150.0
        assert result["discounts"] == 15.0
        assert result["tax"] == 10.5
        assert result["refunds"] == 4.0
        assert result["net_sales"] == 131.0
        assert result["total_orders"] == 4
        assert result["payment_methods"] == {"cash": 140.0, "card": 10.0}
        assert len(result["daily"]) == 2
        assert result["daily"][0]["refunds"] == 4.0
        assert result["daily"][1]["refunds"] == 0.0


class TestLoyaltyReport:
    def test_shape_and_totals(self, patched_repo):
        result = ReportService.get_loyalty_report(None, 1, date(2026, 1, 1), date(2026, 1, 31))
        assert result["total_customers"] == 2
        assert result["total_points_earned"] == 15
        assert result["total_points_redeemed"] == 2
        assert result["total_orders"] == 3
        assert len(result["customers"]) == 2
        assert result["customers"][0]["orders"] == 3
        assert result["customers"][1]["orders"] == 0
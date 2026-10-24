"""Reports cover one branch the caller holds the permission at (Phase 35c ②)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.scope_fixtures import API, as_, sales, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def _sales(client: TestClient, today: str, headers, branch: int | None = None):
    query = f"?date_from={today}&date_to={today}" + (f"&branch_id={branch}" if branch else "")
    return client.get(f"{API}/reports/sales{query}", headers=headers)


class TestSales:
    def test_without_branch_id_it_is_the_active_branch_not_every_branch(self, client: TestClient, world, sales, as_):
        assert _sales(client, sales, as_("sa", "A")).json()["data"]["total_sales"] == 100
        assert _sales(client, sales, as_("sa", "B")).json()["data"]["total_sales"] == 250

    def test_without_branch_id_or_x_branch_id_is_401(self, client: TestClient, world, sales, as_):
        assert _sales(client, sales, as_("sa")).status_code == 401
        assert _sales(client, sales, as_("sa"), world.B).json()["data"]["total_sales"] == 250

    def test_a_branch_where_the_permission_is_not_held_is_404(self, client: TestClient, world, sales, as_):
        assert _sales(client, sales, as_("ba_a", "A"), world.B).status_code == 404
        assert _sales(client, sales, as_("ba_a", "A"), world.A).json()["data"]["total_sales"] == 100
        # Manager at A, Cashier (no reports) at B.
        assert _sales(client, sales, as_("mixed", "B")).status_code == 404
        assert _sales(client, sales, as_("mixed", "A")).status_code == 200


@pytest.mark.parametrize("path", [
    "/reports/daily-summary?date={d}",
    "/reports/financial?date_from={d}&date_to={d}",
    "/reports/inventory?x=1",
])
def test_other_reports_are_scoped_the_same_way(client: TestClient, world, sales, as_, path):
    url = API + path.format(d=sales)
    assert client.get(url + f"&branch_id={world.B}", headers=as_("ba_a", "A")).status_code == 404
    assert client.get(url, headers=as_("ba_a")).status_code == 401
    resp = client.get(url, headers=as_("ba_a", "A"))
    assert resp.status_code == 200
    if "daily-summary" in path:
        assert resp.json()["data"]["total_revenue"] == 100


@pytest.mark.parametrize("path", ["/reports/ecommerce/dashboard", "/reports/loyalty?from_date={d}&to_date={d}"])
def test_organization_wide_reports_need_an_organization_wide_role(client: TestClient, world, sales, as_, path):
    url = API + path.format(d=sales)
    assert client.get(url, headers=as_("ba_a", "A")).status_code == 403
    assert client.get(url, headers=as_("orgmgr")).status_code == 200

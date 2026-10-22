"""Promotions API contract regression tests (Issue 5).

Pins the deliberately asymmetrical arrangement: promotions are the only
domain mounted under `/api` (not `/api/v1`) and are the only routes exempt
from the standard response envelope. These paths/shapes must not silently
drift when other routers are refactored to `/api/v1`.
"""
from __future__ import annotations

from app.main import create_app
from app.middleware.envelope import RAW_PREFIXES


def test_promotions_prefix_and_routes():
    app = create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/promotions" in paths
    assert "/api/admin/promotions" in paths
    assert "/api/admin/promotions/bulk" in paths


def test_promotions_envelope_carve_out_stable():
    """The raw-payload exemption for promotions prefixes must not drift."""
    assert "/api/promotions" in RAW_PREFIXES
    assert "/api/admin/promotions" in RAW_PREFIXES
    assert len(RAW_PREFIXES) == 6


def test_no_other_domain_uses_plain_api_prefix():
    """Every domain except promotions must use /api/v1 (contract consistency)."""
    app = create_app()
    non_v1 = {
        route.path
        for route in app.routes
        if hasattr(route, "path")
        and route.path.startswith("/api/")
        and not route.path.startswith("/api/v1/")
        and route.path != "/api/promotions"
        and route.path != "/api/admin/promotions"
        and route.path != "/api/admin/promotions/bulk"
    }
    assert not non_v1, f"unexpected non-v1 api routes: {sorted(non_v1)}"

"""Which routes need a permission, which only a login, which nothing (offline).

A new route that only asks for ``get_current_user`` fails here until it is
added to ``LOGIN_ONLY`` on purpose: any logged-in account (a registered or
Google user without a role) can call it.
"""
from fastapi.routing import APIRoute

from app.main import create_app
from app.middleware.auth import get_current_user, require_station_item_permission

PREFIX = "/api/v1"

#: Login is enough; the route only returns the caller's own data, or checks
#: access itself.
LOGIN_ONLY = {
    ("GET", "/auth/me"),
    ("POST", "/auth/logout"),
    # Branch picker after login; organization-scoped, no personal data.
    ("GET", "/branches/"),
    ("GET", "/branches/{branch_id}"),
    # Role and permission catalogue; organization-scoped, no personal data.
    ("GET", "/roles/"),
    ("GET", "/roles/permissions/all"),
    ("GET", "/roles/{role_id}"),
    # payments.create, or the caller created the order (checked in the router).
    ("POST", "/slip-verify/upload"),
    ("POST", "/slip-verify/checkslip"),
    # kds.<station>.update of the item's station (require_station_item_permission).
    ("PATCH", "/orders/{order_id}/station-items/{run_id}/status"),
}

PUBLIC = {
    ("GET", "/auth/google"),
    ("GET", "/auth/google/callback"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/register"),
    ("GET", "/orders/track/public/{token}"),
    ("GET", "/wine-products/"),
    ("GET", "/wine-products/{wine_product_id}"),
    ("GET", "/api/promotions"),
    ("GET", "/health"),
    ("GET", "/health/mongodb"),
}


def _calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def _classify(route: APIRoute) -> str:
    calls = list(_calls(route.dependant))
    if any(getattr(c, "__qualname__", "").endswith("permission_checker") for c in calls):
        return "permission"
    if get_current_user in calls:
        return "login"
    return "public"


def _routes() -> dict[tuple[str, str], str]:
    out = {}
    for route in create_app().routes:
        if isinstance(route, APIRoute):
            path = route.path.removeprefix(PREFIX)
            for method in route.methods:
                out[(method, path)] = _classify(route)
    return out


def test_login_only_routes_are_the_reviewed_ones():
    routes = _routes()
    assert {key for key, kind in routes.items() if kind == "login"} == LOGIN_ONLY


def test_public_routes_are_the_reviewed_ones():
    routes = _routes()
    assert {key for key, kind in routes.items() if kind == "public"} == PUBLIC


def test_slip_reads_need_slip_verification_read():
    routes = _routes()
    for key in (
        ("GET", "/slip-verify/{verification_id}"),
        ("GET", "/slip-verify/order/{order_id}"),
        ("GET", "/slip-verify/list"),
    ):
        assert routes[key] == "permission", key


def test_station_item_route_checks_its_station():
    app = create_app()
    (route,) = [
        r for r in app.routes
        if isinstance(r, APIRoute) and r.path.endswith("/station-items/{run_id}/status")
    ]
    assert require_station_item_permission in list(_calls(route.dependant))


#: Organization-wide data: a role held at one branch does not reach it
#: (``require_permission(..., scope="org")``, app/middleware/access.py).
ORG_LEVEL_PERMISSIONS = {
    "catalog.create",
    "promotions.create", "promotions.update", "promotions.delete",
    "coupons.create", "coupons.update", "coupons.delete",
    "branches.create", "branches.update", "branches.delete",
    "roles.create", "roles.update", "roles.delete",
    "audit.read",
}


def _permission_checks(route: APIRoute) -> list[tuple[str, str]]:
    return [
        (c.permission_code, c.scope)
        for c in _calls(route.dependant)
        if getattr(c, "__qualname__", "").endswith("permission_checker")
    ]


def test_organization_level_permissions_are_checked_at_organization_level():
    checks = {
        (method, route.path.removeprefix(PREFIX)): check
        for route in create_app().routes if isinstance(route, APIRoute)
        for method in route.methods
        for check in _permission_checks(route)
    }
    wrong = {key: check for key, check in checks.items() if check[0] in ORG_LEVEL_PERMISSIONS and check[1] != "org"}
    assert wrong == {}
    assert {code for code, scope in checks.values() if scope == "org"} <= ORG_LEVEL_PERMISSIONS | {"reports.read"}

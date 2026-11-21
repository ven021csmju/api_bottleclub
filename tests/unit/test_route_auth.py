"""Which routes need a permission, which only a login, which nothing (offline).

A new route that only asks for ``get_current_user`` fails here until it is
added to ``LOGIN_ONLY`` on purpose: any logged-in account (a registered or
Google user without a role) can call it. One that asks for
``get_authenticated_user`` must also be in ``BEFORE_PASSWORD_CHANGE``: a user
who still has to change their password can call it.
"""
from fastapi.routing import APIRoute

from app.main import create_app
from app.middleware.auth import (
    get_authenticated_user,
    get_current_user,
    require_station_item_permission,
)
from app.middleware.customer_auth import get_customer_account

PREFIX = "/api/v1"

#: Login is enough; the route only returns the caller's own data, or checks
#: access itself.
LOGIN_ONLY = {
    ("GET", "/auth/me"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/change-password"),
    # Branch picker after login: the caller's own branches only (38b).
    ("GET", "/branches/"),
    ("GET", "/branches/{branch_id}"),
    # (The role and permission catalogue needs roles.read since Phase 40.)
    # payments.create, or the caller created the order (checked in the router).
    ("POST", "/slip-verify/upload"),
    ("POST", "/slip-verify/checkslip"),
    # kds.<station>.update of the item's station (require_station_item_permission).
    ("PATCH", "/orders/{order_id}/station-items/{run_id}/status"),
}

#: Callable with must_change_password set (no PASSWORD_CHANGE_REQUIRED).
BEFORE_PASSWORD_CHANGE = {
    ("POST", "/auth/logout"),
    ("POST", "/auth/change-password"),
}

PUBLIC = {
    ("GET", "/auth/google"),
    ("GET", "/auth/google/callback"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/register"),
    # Customer LINE Login: the callback hands a one-time code, exchanged for a customer token.
    ("GET", "/auth/line"),
    ("GET", "/auth/line/callback"),
    ("POST", "/auth/exchange"),
    ("GET", "/orders/track/public/{token}"),
    ("POST", "/orders/track"),
    ("GET", "/wine-products/"),
    ("GET", "/wine-products/{wine_product_id}"),
    ("GET", "/storefront/products"),
    ("GET", "/storefront/products/{product_id}"),
    ("GET", "/api/promotions"),
    ("GET", "/health"),
    ("GET", "/health/mongodb"),
}


#: A customer token only (app/middleware/customer_auth.py); a staff token is refused.
CUSTOMER = {
    ("GET", "/customer/me"),
}

#: Staff with the permission, or X-Service-Key with the scope (024); None:
#: staff only, a valid key gets 403 (the list: a key finds one customer).
SERVICE_KEY = {
    ("GET", "/customers/"): ("customers.read", None),
    ("POST", "/customers/"): ("customers.create", "customers.create"),
    ("GET", "/loyalty/balance/{customer_id}"): ("loyalty.read", "loyalty.read"),
}

#: X-Service-Key only (a staff token is refused).
SERVICE_KEY_ONLY = {
    ("POST", "/customers/lookup"): "customers.lookup",
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
    if get_authenticated_user in calls:
        return "login, before password change"
    if get_customer_account in calls:
        return "customer"
    if any(getattr(c, "__qualname__", "").startswith("require_service_key.") for c in calls):
        return "service key"
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
    assert {key for key, kind in routes.items() if kind.startswith("login")} == LOGIN_ONLY


def test_routes_open_before_the_password_change_are_the_reviewed_ones():
    routes = _routes()
    assert {key for key, kind in routes.items() if kind == "login, before password change"} == (
        BEFORE_PASSWORD_CHANGE
    )


def test_public_routes_are_the_reviewed_ones():
    routes = _routes()
    assert {key for key, kind in routes.items() if kind == "public"} == PUBLIC


def test_customer_routes_are_the_reviewed_ones():
    routes = _routes()
    assert {key for key, kind in routes.items() if kind == "customer"} == CUSTOMER


def test_service_key_routes_are_the_reviewed_ones():
    found = {}
    for route in create_app().routes:
        if isinstance(route, APIRoute):
            for call in _calls(route.dependant):
                if getattr(call, "__qualname__", "").startswith("require_permission_or_service_key."):
                    for method in route.methods:
                        found[(method, route.path.removeprefix(PREFIX))] = (call.permission_code,
                                                                            call.key_scope)
    assert found == SERVICE_KEY


def test_service_key_only_routes_are_the_reviewed_ones():
    found = {}
    for route in create_app().routes:
        if isinstance(route, APIRoute):
            for call in _calls(route.dependant):
                if getattr(call, "__qualname__", "").startswith("require_service_key."):
                    for method in route.methods:
                        found[(method, route.path.removeprefix(PREFIX))] = call.scope
    assert found == SERVICE_KEY_ONLY
    routes = _routes()
    assert {key for key, kind in routes.items() if kind == "service key"} == set(SERVICE_KEY_ONLY)


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
    "branches.create", "branches.delete",
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
    assert {code for code, scope in checks.values() if scope == "org"} <= ORG_LEVEL_PERMISSIONS | {"reports.read", "users.assign_roles"}


def test_branch_update_is_checked_at_the_branch_of_the_path():
    """A branch admin edits the branches where the role is held (Phase 35d)."""
    (route,) = [
        r for r in create_app().routes
        if isinstance(r, APIRoute) and r.path == f"{PREFIX}/branches/{{branch_id}}" and "PUT" in r.methods
    ]
    assert _permission_checks(route) == [("branches.update", "any")]


def test_post_refunds_is_gone():
    """38a: refunds come from returns and POST /payments/{order_id}/refund only."""
    routes = _routes()
    assert ("POST", "/refunds/") not in routes
    assert ("GET", "/refunds/") in routes

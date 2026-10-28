"""No token → 401 on every route that needs a login (Phase 40, item 3).

Up to v0.1.14 the Authorization header was a required parameter: without it
FastAPI answered 422 VALIDATION_ERROR ("Field required"), mixed with any
other missing query or body field. A wrong token already gave 401.

The routes are read from the app itself, so a new route is covered too.
"""
from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.auth import requires_login

pytestmark = pytest.mark.integration


def _routes(login: bool) -> list[tuple[str, str]]:
    out = []
    for route in app.routes:
        if isinstance(route, APIRoute) and requires_login(route) == login:
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            out += [(m, path) for m in sorted(route.methods - {"HEAD", "OPTIONS"})]
    return out


LOGIN = _routes(True)
OPEN = _routes(False)


def test_the_app_has_both_kinds():
    assert len(LOGIN) > 120 and ("POST", "/api/v1/auth/login") in OPEN


@pytest.mark.parametrize("method,path", LOGIN)
def test_no_token_is_401(client: TestClient, method: str, path: str):
    # no body and no query either: the missing token must win over a 422
    resp = client.request(method, path)
    assert resp.status_code == 401, (method, path, resp.status_code, resp.text[:200])
    assert resp.json()["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("header", ["", "Basic abc", "Bearer not-a-jwt"])
@pytest.mark.parametrize("method,path", [("GET", "/api/v1/auth/me"), ("GET", "/api/v1/orders/"),
                                         ("POST", "/api/v1/orders/"), ("GET", "/api/v1/reports/daily-summary")])
def test_a_wrong_token_is_401_too(client: TestClient, method: str, path: str, header: str):
    # an incomplete body too: the token is checked before the body is reported
    resp = client.request(method, path, headers={"Authorization": header}, json={})
    assert resp.status_code == 401, (header, resp.status_code, resp.text[:200])


def test_routes_without_a_login_are_unchanged(client: TestClient):
    assert client.get("/health").status_code == 200
    resp = client.post("/api/v1/auth/login", json={})
    assert (resp.status_code, resp.json()["code"]) == (422, "VALIDATION_ERROR")

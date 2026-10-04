"""Opt-in tests that call a running Central API over HTTP.

These tests are deliberately skipped unless explicitly enabled. They must use
dedicated test credentials and records; no secrets belong in the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator

import httpx
import pytest


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _enabled("RUN_REAL_INTEGRATION_TESTS"):
        return
    marker = pytest.mark.skip(
        reason="Set RUN_REAL_INTEGRATION_TESTS=true to call a real API"
    )
    for item in items:
        if "real_integration" in str(item.fspath):
            item.add_marker(marker)


@dataclass(frozen=True)
class RealApiSettings:
    base_url: str
    user_username: str
    user_password: str
    admin_username: str
    admin_password: str
    limited_username: str | None
    limited_password: str | None
    branch_id: str
    other_branch_id: str | None
    product_id: str | None
    other_org_order_id: str | None
    checkout_order_id: str | None
    checkout_amount: str | None
    slip_id: str | None
    approve_slip_id: str | None
    reject_slip_id: str | None
    allow_mutations: bool
    allow_checkout: bool
    allow_slip_moderation: bool


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"Missing required real integration setting: {name}")
    return value


@pytest.fixture(scope="session")
def real_settings() -> RealApiSettings:
    return RealApiSettings(
        base_url=os.getenv("REAL_API_BASE_URL", "https://api.wayneven.uk").rstrip("/"),
        user_username=_required("TEST_USER_USERNAME"),
        user_password=_required("TEST_USER_PASSWORD"),
        admin_username=_required("TEST_ADMIN_USERNAME"),
        admin_password=_required("TEST_ADMIN_PASSWORD"),
        limited_username=os.getenv("TEST_LIMITED_USERNAME") or None,
        limited_password=os.getenv("TEST_LIMITED_PASSWORD") or None,
        branch_id=_required("TEST_BRANCH_ID"),
        other_branch_id=os.getenv("TEST_OTHER_BRANCH_ID") or None,
        product_id=os.getenv("TEST_PRODUCT_ID") or None,
        other_org_order_id=os.getenv("TEST_OTHER_ORG_ORDER_ID") or None,
        checkout_order_id=os.getenv("TEST_CHECKOUT_ORDER_ID") or None,
        checkout_amount=os.getenv("TEST_CHECKOUT_AMOUNT") or None,
        slip_id=os.getenv("TEST_SLIP_ID") or None,
        approve_slip_id=os.getenv("TEST_APPROVE_SLIP_ID") or None,
        reject_slip_id=os.getenv("TEST_REJECT_SLIP_ID") or None,
        allow_mutations=_enabled("ALLOW_REAL_MUTATIONS"),
        allow_checkout=_enabled("ALLOW_REAL_CHECKOUT"),
        allow_slip_moderation=_enabled("ALLOW_REAL_SLIP_MODERATION"),
    )


@pytest.fixture(scope="session")
def api_client(real_settings: RealApiSettings) -> Iterator[httpx.Client]:
    with httpx.Client(
        base_url=real_settings.base_url,
        timeout=httpx.Timeout(30.0),
        follow_redirects=False,
    ) as client:
        yield client


def login(client: httpx.Client, username: str, password: str) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    data = body.get("data", body)
    assert isinstance(data.get("access_token"), str)
    assert data.get("token_type") == "bearer"
    return data


@pytest.fixture(scope="session")
def user_token(api_client: httpx.Client, real_settings: RealApiSettings) -> str:
    return login(
        api_client, real_settings.user_username, real_settings.user_password
    )["access_token"]


@pytest.fixture(scope="session")
def admin_token(api_client: httpx.Client, real_settings: RealApiSettings) -> str:
    return login(
        api_client, real_settings.admin_username, real_settings.admin_password
    )["access_token"]


@pytest.fixture(scope="session")
def limited_token(api_client: httpx.Client, real_settings: RealApiSettings) -> str:
    if not real_settings.limited_username or not real_settings.limited_password:
        pytest.skip("TEST_LIMITED_USERNAME and TEST_LIMITED_PASSWORD are required")
    return login(
        api_client,
        real_settings.limited_username,
        real_settings.limited_password,
    )["access_token"]


def auth_headers(token: str, branch_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if branch_id is not None:
        headers["X-Branch-Id"] = branch_id
    return headers


@pytest.fixture
def user_headers(user_token: str, real_settings: RealApiSettings) -> dict[str, str]:
    return auth_headers(user_token, real_settings.branch_id)


@pytest.fixture
def admin_headers(admin_token: str, real_settings: RealApiSettings) -> dict[str, str]:
    return auth_headers(admin_token, real_settings.branch_id)


def response_data(response: httpx.Response) -> dict:
    body = response.json()
    return body.get("data", body)


def require_mutation(settings: RealApiSettings) -> None:
    if not settings.allow_mutations:
        pytest.skip("Set ALLOW_REAL_MUTATIONS=true for real order mutations")

import pytest

from .conftest import auth_headers, response_data


def test_valid_branch_can_list_orders(api_client, admin_headers):
    response = api_client.get(
        "/api/v1/orders/?page=1&per_page=1", headers=admin_headers
    )
    assert response.status_code == 200, response.text
    data = response_data(response)
    assert {"orders", "total", "page", "per_page"}.issubset(data)


def test_missing_branch_header_is_rejected(api_client, admin_token):
    response = api_client.get(
        "/api/v1/orders/?page=1&per_page=1",
        headers=auth_headers(admin_token),
    )
    assert response.status_code in {401, 422}, response.text


def test_user_cannot_use_other_branch(api_client, admin_token, real_settings):
    if not real_settings.other_branch_id:
        pytest.skip("TEST_OTHER_BRANCH_ID is not configured")
    response = api_client.get(
        "/api/v1/orders/?page=1&per_page=1",
        headers=auth_headers(admin_token, real_settings.other_branch_id),
    )
    assert response.status_code == 403, response.text


def test_no_authorization_is_rejected(api_client):
    response = api_client.get("/api/v1/catalog/products?page=1&per_page=1")
    assert response.status_code in {401, 422}, response.text


def test_user_without_order_permission_is_rejected(api_client, limited_token, real_settings):
    response = api_client.get(
        "/api/v1/orders/?page=1&per_page=1",
        headers=auth_headers(limited_token, real_settings.branch_id),
    )
    assert response.status_code == 403, response.text


def test_other_organization_order_is_not_visible(
    api_client, admin_headers, real_settings
):
    if not real_settings.other_org_order_id:
        pytest.skip("TEST_OTHER_ORG_ORDER_ID is not configured")
    response = api_client.get(
        f"/api/v1/orders/{real_settings.other_org_order_id}",
        headers=admin_headers,
    )
    assert response.status_code in {403, 404}, response.text

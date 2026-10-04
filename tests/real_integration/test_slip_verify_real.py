import pytest

from .conftest import auth_headers, require_mutation, response_data


def test_slip_read_is_scoped_and_authenticated(
    api_client, admin_token, real_settings
):
    if not real_settings.slip_id:
        pytest.skip("TEST_SLIP_ID is not configured")
    response = api_client.get(
        f"/api/v1/slip-verify/{real_settings.slip_id}",
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    data = response_data(response)
    assert data["id"] == int(real_settings.slip_id)
    assert "status" in data
    assert "order_id" in data


def test_slip_list_authorization(api_client, admin_token, limited_token):
    allowed = api_client.get(
        "/api/v1/slip-verify/list", headers=auth_headers(admin_token)
    )
    assert allowed.status_code == 200, allowed.text

    response = api_client.get(
        "/api/v1/slip-verify/list", headers=auth_headers(limited_token)
    )
    assert response.status_code == 403, response.text


def test_slip_moderation_permissions(
    api_client, limited_token, real_settings
):
    if not real_settings.approve_slip_id or not real_settings.reject_slip_id:
        pytest.skip("TEST_APPROVE_SLIP_ID and TEST_REJECT_SLIP_ID are required")
    headers = auth_headers(limited_token)
    approve = api_client.post(
        f"/api/v1/slip-verify/{real_settings.approve_slip_id}/approve",
        headers=headers,
        json={},
    )
    reject = api_client.post(
        f"/api/v1/slip-verify/{real_settings.reject_slip_id}/reject",
        headers=headers,
        json={},
    )
    assert approve.status_code == 403, approve.text
    assert reject.status_code == 403, reject.text


def test_approve_slip_real_transaction(api_client, admin_headers, real_settings):
    require_mutation(real_settings)
    if not real_settings.allow_slip_moderation:
        pytest.skip("Set ALLOW_REAL_SLIP_MODERATION=true for slip approval")
    if not real_settings.approve_slip_id:
        pytest.skip("TEST_APPROVE_SLIP_ID is not configured")

    response = api_client.post(
        f"/api/v1/slip-verify/{real_settings.approve_slip_id}/approve",
        headers=admin_headers,
        json={"note": "real integration test"},
    )
    assert response.status_code == 200, response.text
    assert response_data(response)["status"] == "verified"


def test_reject_slip_real_transaction(api_client, admin_headers, real_settings):
    require_mutation(real_settings)
    if not real_settings.allow_slip_moderation:
        pytest.skip("Set ALLOW_REAL_SLIP_MODERATION=true for slip rejection")
    if not real_settings.reject_slip_id:
        pytest.skip("TEST_REJECT_SLIP_ID is not configured")

    response = api_client.post(
        f"/api/v1/slip-verify/{real_settings.reject_slip_id}/reject",
        headers=admin_headers,
        json={"note": "real integration test"},
    )
    assert response.status_code == 200, response.text
    assert response_data(response)["status"] == "rejected"

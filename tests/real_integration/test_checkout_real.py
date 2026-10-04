import pytest

from .conftest import require_mutation, response_data


def test_checkout_existing_test_order(api_client, admin_headers, real_settings):
    require_mutation(real_settings)
    if not real_settings.allow_checkout:
        pytest.skip("Set ALLOW_REAL_CHECKOUT=true for checkout mutation")
    if not real_settings.checkout_order_id or not real_settings.checkout_amount:
        pytest.skip("TEST_CHECKOUT_ORDER_ID and TEST_CHECKOUT_AMOUNT are required")

    response = api_client.post(
        f"/api/v1/orders/{real_settings.checkout_order_id}/checkout",
        headers=admin_headers,
        json={
            "payments": [
                {
                    "payment_method": "bank_transfer",
                    "amount": real_settings.checkout_amount,
                    "external_reference": "real-integration-test",
                }
            ],
            "earn_points": True,
            "idempotency_key": "real-integration-checkout",
        },
    )
    assert response.status_code == 200, response.text
    data = response_data(response)
    assert data["id"] == int(real_settings.checkout_order_id)
    assert data["status"] in {"paid", "completed"}
    assert data["amount_paid"]

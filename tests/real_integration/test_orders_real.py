import uuid

import pytest

from .conftest import require_mutation, response_data


def _product(api_client, headers, product_id):
    response = api_client.get(
        f"/api/v1/catalog/products/{product_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    product = response_data(response)
    assert product["id"] == int(product_id)
    assert product["selling_price"] is not None
    return product


def test_create_order_get_order_and_cancel_cleanup(
    api_client, admin_headers, real_settings
):
    require_mutation(real_settings)
    if not real_settings.product_id:
        pytest.skip("TEST_PRODUCT_ID is not configured")

    product = _product(api_client, admin_headers, real_settings.product_id)
    payload = {
        "branch_id": int(real_settings.branch_id),
                "items": [
            {
                "product_id": int(real_settings.product_id),
                "quantity": 1,
                "unit_price": str(product["selling_price"]),
            }
        ],
        "order_source": "ecommerce",
        "idempotency_key": f"real-api-test-{uuid.uuid4()}",
    }
    created = api_client.post(
        "/api/v1/orders/", headers=admin_headers, json=payload
    )
    assert created.status_code == 200, created.text
    order = response_data(created)
    assert order["id"]
    assert order["order_source"] == "ecommerce"
    assert order["grand_total"] == str(product["selling_price"])
    assert order["status"] == "pending"

    fetched = api_client.get(
        f"/api/v1/orders/{order['id']}", headers=admin_headers
    )
    assert fetched.status_code == 200, fetched.text
    fetched_order = response_data(fetched)
    assert fetched_order["id"] == order["id"]
    assert fetched_order["order_source"] == "ecommerce"

    cancelled = api_client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        headers=admin_headers,
        json={"reason": "real integration test cleanup"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert response_data(cancelled)["status"] == "cancelled"


def test_client_price_cannot_override_catalog_price(
    api_client, admin_headers, real_settings
):
    require_mutation(real_settings)
    if not real_settings.product_id:
        pytest.skip("TEST_PRODUCT_ID is not configured")

    product = _product(api_client, admin_headers, real_settings.product_id)
    response = api_client.post(
        "/api/v1/orders/",
        headers=admin_headers,
        json={
            "branch_id": int(real_settings.branch_id),
            "items": [
                {
                    "product_id": int(real_settings.product_id),
                    "quantity": 1,
                    "unit_price": "0.01",
                }
            ],
            "order_source": "ecommerce",
            "idempotency_key": f"real-api-price-test-{uuid.uuid4()}",
        },
    )
    assert response.status_code == 400, response.text
    assert response_data(response).get("code") == "PRICE_MISMATCH" or "PRICE_MISMATCH" in response.text

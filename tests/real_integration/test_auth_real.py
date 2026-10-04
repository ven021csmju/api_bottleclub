from .conftest import auth_headers, login, response_data


def test_login_success(api_client, real_settings):
    token_data = login(
        api_client,
        real_settings.user_username,
        real_settings.user_password,
    )
    response = api_client.get(
        "/api/v1/auth/me",
        headers=auth_headers(token_data["access_token"]),
    )
    assert response.status_code == 200, response.text
    profile = response_data(response)
    assert profile["username"] == real_settings.user_username
    assert profile["id"]


def test_login_invalid_password(api_client, real_settings):
    response = api_client.post(
        "/api/v1/auth/login",
        json={
            "username": real_settings.user_username,
            "password": f"{real_settings.user_password}__invalid",
        },
    )
    assert response.status_code == 401, response.text


def test_login_invalid_username(api_client, real_settings):
    response = api_client.post(
        "/api/v1/auth/login",
        json={
            "username": f"{real_settings.user_username}__invalid",
            "password": real_settings.user_password,
        },
    )
    assert response.status_code == 401, response.text


def test_invalid_access_token_is_rejected(api_client):
    response = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401, response.text

from fastapi.testclient import TestClient

from app.config.settings import settings


class TestErrorContract:
    def test_validation_error_shape(self, client: TestClient):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 422
        body = resp.json()
        assert {"detail", "code", "request_id"} == set(body)
        assert body["code"] == "VALIDATION_ERROR"
        assert resp.headers.get("X-Request-Id")

    def test_not_found_shape(self, client: TestClient):
        resp = client.get("/api/v1/does-not-exist")
        assert resp.status_code == 404
        body = resp.json()
        assert {"detail", "code", "request_id"} == set(body)
        assert body["code"] == "NOT_FOUND"

    def test_request_id_injected(self, client: TestClient, seed_user: dict):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": seed_user["username"], "password": "wrong"},
        )
        assert resp.json()["request_id"]


class TestEnvelope:
    def test_paginated_response_meta(self, client: TestClient, auth_headers: dict, seed_branch: int):
        resp = client.get("/api/v1/orders", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert {"data", "meta", "request_id"} == set(body)
        assert body["meta"] == {"page": 1, "per_page": 20, "total": 0}

    def test_health_is_raw(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    def test_openapi_schema_is_raw(self, client: TestClient):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "paths" in body
        assert "request_id" not in body


class TestRateLimit:
    def test_login_hits_rate_limit(self, client: TestClient):
        if not settings.RATE_LIMIT_ENABLED:
            import pytest

            pytest.skip("rate limiting disabled")

        statuses = []
        for _ in range(60):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "ghost", "password": "nope"},
            )
            statuses.append(resp.status_code)
            if resp.status_code == 429:
                body = resp.json()
                assert {"detail", "code", "request_id"} == set(body)
                assert body["code"] == "RATE_LIMIT_EXCEEDED"
                break
        else:
            raise AssertionError("expected a 429 after exceeding login rate limit")

        assert any(code == 429 for code in statuses)
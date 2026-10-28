"""POST /slip-verify/checkslip is deprecated (Phase 40, item 8): still served,
marked in OpenAPI, and every answer (errors too) carries Deprecation."""
from fastapi.testclient import TestClient

from app.main import create_app


def test_marked_in_openapi_and_upload_is_not():
    paths = create_app().openapi()["paths"]
    assert paths["/api/v1/slip-verify/checkslip"]["post"].get("deprecated") is True
    assert not paths["/api/v1/slip-verify/upload"]["post"].get("deprecated")


def test_every_answer_says_so():
    with TestClient(create_app()) as client:
        resp = client.post("/api/v1/slip-verify/checkslip")  # no token: 401, still marked
        upload = client.post("/api/v1/slip-verify/upload")
    assert resp.status_code == 401
    assert resp.headers["Deprecation"] == "true"
    assert resp.headers["Link"] == '</api/v1/slip-verify/upload>; rel="successor-version"'
    assert "Deprecation" not in upload.headers

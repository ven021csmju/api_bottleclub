"""The envelope keeps every header of the answer it wraps (Phase 45).

Up to v0.1.19 it copied the headers into a dict: of two ``Set-Cookie`` only
the last one was sent (GET /auth/google/callback deletes two cookies; the
refresh cookie is set beside others).
"""
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.middleware.envelope import ResponseEnvelopeMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ResponseEnvelopeMiddleware)

    @app.get("/api/v1/two-cookies")
    def two_cookies(response: Response) -> dict:
        response.set_cookie("a", "1", httponly=True)
        response.set_cookie("b", "2", secure=True)
        response.headers["X-Other"] = "kept"
        return {"ok": True}

    @app.get("/api/v1/enveloped")
    def enveloped(response: Response) -> dict:
        response.set_cookie("a", "1")
        response.delete_cookie("b")
        return {"data": {"ok": True}, "request_id": "r-1"}

    return app


def _set_cookies(resp) -> list[str]:
    return [v.split("=")[0] for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]


def test_a_wrapped_answer_keeps_both_cookies():
    resp = TestClient(_app()).get("/api/v1/two-cookies")
    assert resp.json()["data"] == {"ok": True}
    assert _set_cookies(resp) == ["a", "b"]
    assert resp.headers["X-Other"] == "kept"
    assert resp.headers["content-type"] == "application/json"
    assert int(resp.headers["content-length"]) == len(resp.content)


def test_an_enveloped_answer_keeps_both_cookies():
    resp = TestClient(_app()).get("/api/v1/enveloped")
    assert resp.json()["data"] == {"ok": True}
    assert _set_cookies(resp) == ["a", "b"]

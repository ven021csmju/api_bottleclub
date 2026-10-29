"""CORS origins (Phase 44): no default, exact origins only, production must set them.

The API sends credentials, so an origin is exact (scheme://host[:port], no
path, no trailing /, no "*") and never a regex; production without
CORS_ORIGINS does not start. v0.1.17 allowed two real Vercel apps and
localhost by default, accepted any string and only a JSON list.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config.settings import Settings, parse_cors_origins

SHOP = [
    "https://pos-thebottleclub-web-eta.vercel.app",
    "https://admin-pos-wine.vercel.app",
    "https://the-bottle-club.vercel.app",
    "https://pos.wayneven.uk",
    "https://admin.wayneven.uk",
    "https://shop.wayneven.uk",
]
OTHERS = [
    "https://evil.vercel.app",
    # Vercel preview / branch URLs of the same projects
    "https://pos-thebottleclub-web-git-main-thebottleclub.vercel.app",
    "https://pos-thebottleclub-web-eta-3k9x2abcd.vercel.app",
    "https://admin-pos-wine-git-feature-x.vercel.app",
    "https://the-bottle-club-ai.vercel.app",
    "https://front-posimon.vercel.app",
    "https://evil.pos.wayneven.uk",
    "https://pos.wayneven.uk.evil.com",
    "http://pos.wayneven.uk",
    "https://pos.wayneven.uk:8443",
    "http://localhost:5173",
    "null",
]
_SECURE_JWT = "a-very-secure-secret-key-that-is-long-enough-32"
_PROD_DB_URL = "postgresql+psycopg://user:s3cr3t-pw@prod-host:5432/prod_db"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _production(**overrides) -> Settings:
    return _settings(ENVIRONMENT="production", DATABASE_URL=_PROD_DB_URL, JWT_SECRET_KEY=_SECURE_JWT, **overrides)


def _client(monkeypatch, origins: str) -> TestClient:
    from app import main

    monkeypatch.setattr(main.settings, "CORS_ORIGINS", origins)
    return TestClient(main.create_app())


# ------------------------------------------------------------------ the value


def test_the_default_is_no_origin(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert _settings().cors_origins == []
    source = Path(__file__).resolve().parents[2].joinpath("app/config/settings.py").read_text(encoding="utf-8")
    for name in ("vercel.app", "posimon", "the-bottle-club", "wayneven"):
        assert name not in source, name


@pytest.mark.parametrize("raw", [
    ",".join(SHOP),
    " , ".join(SHOP) + ",",
    '["' + '", "'.join(SHOP) + '"]',
    ",".join(SHOP + SHOP[:2]),  # repeated: once each
])
def test_comma_separated_or_a_json_list(raw):
    assert parse_cors_origins(raw, "production") == SHOP


def test_from_the_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", ",".join(SHOP))
    assert _production().cors_origins == SHOP


@pytest.mark.parametrize("origin", [
    "*", "https://*.vercel.app", "https://pos-*.vercel.app", "*.wayneven.uk", "https://pos.wayneven.uk*",
])
@pytest.mark.parametrize("environment", ["production", "staging", "development", "test"])
def test_no_wildcard_with_credentials(origin, environment):
    with pytest.raises(ValueError, match="no wildcard"):
        parse_cors_origins(f"https://pos.wayneven.uk,{origin}", environment)
    with pytest.raises(ValueError, match="no wildcard"):
        parse_cors_origins(f'["{origin}"]', environment)


@pytest.mark.parametrize("origin", [
    "https://pos.wayneven.uk/",
    "https://pos.wayneven.uk/pos",
    "https://pos.wayneven.uk?x=1",
    "https://pos.wayneven.uk#top",
    "https://Pos.Wayneven.uk",
    "pos.wayneven.uk",
    "//pos.wayneven.uk",
    "ftp://pos.wayneven.uk",
    "https://user@pos.wayneven.uk",
    "https://",
    "null",
])
def test_only_exact_origins(origin):
    with pytest.raises(ValueError, match="not an origin"):
        parse_cors_origins(origin, "staging")


@pytest.mark.parametrize("raw, reason", [
    ('["https://pos.wayneven.uk"', "not a JSON list"), ("[1, 2]", "JSON list of strings"), ('{"a": 1}', "not an origin"),
])
def test_a_broken_json_list_is_refused(raw, reason):
    with pytest.raises(ValueError, match=reason):
        parse_cors_origins(raw, "staging")


# ------------------------------------------------------------- production


@pytest.mark.parametrize("raw", [None, "", " , "])
def test_production_without_origins_is_refused(monkeypatch, raw):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    extra = {} if raw is None else {"CORS_ORIGINS": raw}
    with pytest.raises(ValidationError, match="CORS_ORIGINS must be set in production") as info:
        _production(**extra)
    # the error names the variable, not the other settings
    assert _SECURE_JWT not in str(info.value) and "s3cr3t-pw" not in str(info.value)


def test_production_is_https_only():
    with pytest.raises(ValidationError, match="https origins only"):
        _production(CORS_ORIGINS="https://pos.wayneven.uk,http://localhost:5173")


@pytest.mark.parametrize("environment", ["staging", "development", "test"])
def test_elsewhere_no_origin_is_allowed(monkeypatch, environment):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    extra = {"DATABASE_URL": _PROD_DB_URL, "JWT_SECRET_KEY": _SECURE_JWT}
    assert _settings(ENVIRONMENT=environment, **extra).cors_origins == []
    assert _settings(ENVIRONMENT=environment, CORS_ORIGINS="http://localhost:5173", **extra).cors_origins == [
        "http://localhost:5173"]


def test_the_app_does_not_start_in_production_without_origins():
    """Fail fast: importing the app (what uvicorn does) exits with the reason."""
    env = {
        "PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"), "PYTHONDONTWRITEBYTECODE": "1",
        "ENVIRONMENT": "production", "DATABASE_URL": _PROD_DB_URL, "JWT_SECRET_KEY": _SECURE_JWT,
        "RABBITMQ_URL": "amqp://none:none@127.0.0.1:1/", "MONGODB_URI": "mongodb://127.0.0.1:1/",
    }
    root = Path(__file__).resolve().parents[2]
    run = subprocess.run([sys.executable, "-c", "import app.main"], cwd=root, env=env,
                         capture_output=True, text=True, timeout=120)
    assert run.returncode != 0
    assert "CORS_ORIGINS must be set in production" in run.stderr
    assert _SECURE_JWT not in run.stderr and "s3cr3t-pw" not in run.stderr
    env["CORS_ORIGINS"] = ",".join(SHOP)
    run = subprocess.run([sys.executable, "-c", "import app.main; print(app.main.settings.cors_origins)"],
                         cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == repr(SHOP)


# --------------------------------------------------------------- the answer


def test_no_regex_and_no_star_in_the_middleware(monkeypatch):
    from app import main

    monkeypatch.setattr(main.settings, "CORS_ORIGINS", ",".join(SHOP))
    (cors,) = [m for m in main.create_app().user_middleware if m.cls is CORSMiddleware]
    assert cors.kwargs.get("allow_origin_regex") is None
    assert cors.kwargs["allow_origins"] == SHOP and cors.kwargs["allow_credentials"] is True


@pytest.mark.parametrize("origin", SHOP)
def test_an_allowed_origin_gets_acao(monkeypatch, origin):
    client = _client(monkeypatch, ",".join(SHOP))
    resp = client.get("/health", headers={"Origin": origin})
    assert resp.headers["access-control-allow-origin"] == origin
    assert resp.headers["access-control-allow-credentials"] == "true"
    pre = client.options("/api/v1/orders/", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,idempotency-key,x-branch-id"})
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", OTHERS)
def test_another_origin_gets_none(monkeypatch, origin):
    client = _client(monkeypatch, ",".join(SHOP))
    resp = client.get("/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in resp.headers
    pre = client.options("/api/v1/orders/", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 400
    assert "access-control-allow-origin" not in pre.headers


def test_no_origin_configured_allows_none(monkeypatch):
    client = _client(monkeypatch, "")
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in resp.headers

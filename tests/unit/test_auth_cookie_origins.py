"""AUTH_COOKIE_ORIGINS (Phase 45): the origins that may use the refresh-token cookie.

Same form as CORS_ORIGINS (exact origins, comma or JSON list, https only in
production); empty by default, also in production (then no origin may use
the cookie). Each one must be in CORS_ORIGINS too, or the app does not
start: the browser could not send the cookie with credentials otherwise.
v0.1.19 had no such setting.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.settings import Settings

POS, ADMIN = "https://pos.wayneven.uk", "https://admin.wayneven.uk"
_SECURE_JWT = "a-very-secure-secret-key-that-is-long-enough-32"
_PROD_DB_URL = "postgresql+psycopg://user:s3cr3t-pw@prod-host:5432/prod_db"


def _settings(environment: str = "production", **overrides) -> Settings:
    return Settings(_env_file=None, ENVIRONMENT=environment, DATABASE_URL=_PROD_DB_URL, JWT_SECRET_KEY=_SECURE_JWT,
                    **overrides)


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    for name in ("CORS_ORIGINS", "AUTH_COOKIE_ORIGINS"):
        monkeypatch.delenv(name, raising=False)


def test_the_default_is_none_even_in_production():
    assert _settings(CORS_ORIGINS=POS).auth_cookie_origins == []


@pytest.mark.parametrize("raw", [POS, f" {POS} ,", f'["{POS}"]', f"{POS},{POS}"])
def test_one_of_the_cors_origins(raw):
    assert _settings(CORS_ORIGINS=f"{POS},{ADMIN}", AUTH_COOKIE_ORIGINS=raw).auth_cookie_origins == [POS]


def test_from_the_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f"{POS},{ADMIN}")
    monkeypatch.setenv("AUTH_COOKIE_ORIGINS", f"{ADMIN},{POS}")
    assert _settings().auth_cookie_origins == [ADMIN, POS]


@pytest.mark.parametrize("environment", ["production", "staging", "development"])
def test_an_origin_outside_cors_is_refused(environment):
    with pytest.raises(ValidationError, match="AUTH_COOKIE_ORIGINS must be in CORS_ORIGINS too: https://shop"):
        _settings(environment, CORS_ORIGINS=POS, AUTH_COOKIE_ORIGINS=f"{POS},https://shop.wayneven.uk")


@pytest.mark.parametrize("origin, reason", [
    ("*", "no wildcard"), ("https://*.wayneven.uk", "no wildcard"), ("https://pos.wayneven.uk/", "not an origin"),
    ("http://pos.wayneven.uk", "production allows https origins only"),
])
def test_the_form_of_cors_origins(origin, reason):
    with pytest.raises(ValidationError, match=f"AUTH_COOKIE_ORIGINS: {reason}") as info:
        _settings(CORS_ORIGINS=POS, AUTH_COOKIE_ORIGINS=origin)
    assert _SECURE_JWT not in str(info.value) and "s3cr3t-pw" not in str(info.value)


def test_staging_takes_localhost():
    """The browser treats http://localhost as a secure context: a Secure cookie works there."""
    local = "http://localhost:5173"
    assert _settings("staging", CORS_ORIGINS=local, AUTH_COOKIE_ORIGINS=local).auth_cookie_origins == [local]


def test_the_app_does_not_start_with_an_origin_outside_cors():
    env = {
        "PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"), "PYTHONDONTWRITEBYTECODE": "1",
        "ENVIRONMENT": "production", "DATABASE_URL": _PROD_DB_URL, "JWT_SECRET_KEY": _SECURE_JWT,
        "RABBITMQ_URL": "amqp://none:none@127.0.0.1:1/", "MONGODB_URI": "mongodb://127.0.0.1:1/",
        "CORS_ORIGINS": POS, "AUTH_COOKIE_ORIGINS": ADMIN,
    }
    root = Path(__file__).resolve().parents[2]
    run = subprocess.run([sys.executable, "-c", "import app.main"], cwd=root, env=env,
                         capture_output=True, text=True, timeout=120)
    assert run.returncode != 0
    assert f"AUTH_COOKIE_ORIGINS must be in CORS_ORIGINS too: {ADMIN}" in run.stderr
    env["CORS_ORIGINS"] = f"{POS},{ADMIN}"
    run = subprocess.run([sys.executable, "-c", "import app.main; print(app.main.settings.auth_cookie_origins)"],
                         cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == repr([ADMIN])

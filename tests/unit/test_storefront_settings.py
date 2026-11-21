"""FRONTEND_URLS, the customer token key and LINE's configuration (offline)."""
import pytest
from jose import JWTError
from pydantic import ValidationError

from app.config import settings as settings_module
from app.config.settings import Settings, parse_frontend_urls
from app.shared import security

_SECURE = "a-very-secure-secret-key-that-is-long-enough-32"
_CUSTOMER = "another-secure-secret-key-for-customers-40c"


@pytest.mark.parametrize("raw", [
    "https://shop.example.com/auth/line/done",
    "https://shop.example.com",
    "https://a.example.com/x, https://b.example.com/y",
])
def test_frontend_urls_accepted(raw):
    assert parse_frontend_urls(raw, "production")


@pytest.mark.parametrize("raw", [
    "https://shop.example.com/done?next=/x",
    "https://shop.example.com/done#frag",
    "https://*.example.com/done",
    "javascript:alert(1)",
    "/relative/path",
    "https://user:pw@shop.example.com/",
])
def test_frontend_urls_refused(raw):
    with pytest.raises(ValueError):
        parse_frontend_urls(raw, "development")


def test_production_frontend_urls_are_https():
    with pytest.raises(ValueError, match="https"):
        parse_frontend_urls("http://localhost:3000/auth/line/done", "production")
    assert parse_frontend_urls("http://localhost:3000/auth/line/done", "development")


def test_customer_key_must_differ_from_the_staff_key():
    with pytest.raises(ValidationError, match="differ"):
        Settings(JWT_SECRET_KEY=_SECURE, CUSTOMER_JWT_SECRET_KEY=_SECURE)


def test_customer_key_must_be_long():
    with pytest.raises(ValidationError, match="32"):
        Settings(CUSTOMER_JWT_SECRET_KEY="short")


def test_line_configured_needs_every_piece():
    full = dict(LINE_CLIENT_ID="1", LINE_CLIENT_SECRET="s", LINE_REDIRECT_URI="https://api.example.com/cb",
                CUSTOMER_JWT_SECRET_KEY=_CUSTOMER, FRONTEND_URLS="https://shop.example.com/done")
    assert Settings(**full).line_login_configured
    for missing in full:
        assert not Settings(**{k: v for k, v in full.items() if k != missing}).line_login_configured, missing


def test_customer_and_staff_tokens_never_decode_as_each_other(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "JWT_SECRET_KEY", _SECURE)
    monkeypatch.setattr(settings_module.settings, "CUSTOMER_JWT_SECRET_KEY", _CUSTOMER)
    customer = security.create_customer_access_token(7, 1)
    staff = security.create_access_token(7, 1, [], [])

    assert security.decode_customer_token(customer)["sub"] == "7"
    with pytest.raises(JWTError):
        security.decode_token(customer)
    with pytest.raises(JWTError):
        security.decode_customer_token(staff)


def test_a_customer_key_token_without_aud_is_refused(monkeypatch):
    """require_aud: a token signed with the customer key but without ``aud``."""
    from jose import jwt

    monkeypatch.setattr(settings_module.settings, "CUSTOMER_JWT_SECRET_KEY", _CUSTOMER)
    token = jwt.encode({"sub": "7", "type": "customer_access", "exp": 4102444800}, _CUSTOMER, algorithm="HS256")
    with pytest.raises(JWTError):
        security.decode_customer_token(token)

"""LINE Login (OpenID Connect) for customers: the calls to LINE.

Every answer from LINE is checked: its status, its JSON, and the ID token's
issuer, audience, nonce and subject at LINE's verify endpoint.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config.settings import settings
from app.shared.exceptions import BadRequestException, UnauthorizedException

AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"
TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"
VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"
LINE_ISSUER = "https://access.line.me"
SCOPE = "profile openid email"
NOT_CONFIGURED = "LINE Login is not configured"
FAILED = "Unable to authenticate with LINE"
logger = logging.getLogger(__name__)


def _configured() -> tuple[str, str, str]:
    if not settings.line_login_configured:
        raise BadRequestException(detail=NOT_CONFIGURED, code="LINE_NOT_CONFIGURED")
    return settings.LINE_CLIENT_ID, settings.LINE_CLIENT_SECRET, settings.LINE_REDIRECT_URI


def ensure_configured() -> None:
    _configured()


def authorization_url(state: str, nonce: str) -> str:
    client_id, _, redirect_uri = _configured()
    params = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": SCOPE,
        "nonce": nonce,
    })
    return f"{AUTHORIZE_URL}?{params}"


def _post(url: str, data: dict[str, str], stage: str) -> dict[str, Any]:
    """POST a form to LINE; the JSON object of a 200, else 401 (only the status
    and the stage are logged, never the code, a token or the secret)."""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, data=data)
    except httpx.HTTPError as exc:
        logger.warning("LINE %s failed: %s", stage, type(exc).__name__)
        raise UnauthorizedException(detail=FAILED, code="LINE_AUTH_FAILED")
    if response.status_code != 200:
        logger.warning("LINE %s answered status=%s", stage, response.status_code)
        raise UnauthorizedException(detail=FAILED, code="LINE_AUTH_FAILED")
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        logger.warning("LINE %s answered no JSON object", stage)
        raise UnauthorizedException(detail=FAILED, code="LINE_AUTH_FAILED")
    return body


def exchange_code(code: str) -> dict[str, Any]:
    client_id, client_secret, redirect_uri = _configured()
    body = _post(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }, "token")
    if not isinstance(body.get("id_token"), str) or not body["id_token"]:
        logger.warning("LINE token answer has no id_token (scope openid missing?)")
        raise UnauthorizedException(detail=FAILED, code="LINE_AUTH_FAILED")
    return body


def verify_id_token(id_token: str, expected_nonce: str) -> dict[str, Any]:
    """The ID token's claims, verified by LINE and checked here again."""
    client_id, _, _ = _configured()
    claims = _post(VERIFY_URL, {"id_token": id_token, "client_id": client_id, "nonce": expected_nonce}, "verify")
    checks = {
        "iss": claims.get("iss") == LINE_ISSUER,
        "aud": claims.get("aud") == client_id,
        "nonce": claims.get("nonce") == expected_nonce,
        "sub": isinstance(claims.get("sub"), str) and bool(claims["sub"]) and len(claims["sub"]) <= 255,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        logger.warning("LINE verify: claim check failed: %s", ",".join(failed))
        raise UnauthorizedException(detail=FAILED, code="LINE_AUTH_FAILED")
    return claims

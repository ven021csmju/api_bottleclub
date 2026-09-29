from __future__ import annotations

from typing import Any

import httpx
from jose import JWTError, jwk, jwt

from app.config.settings import settings
from app.shared.exceptions import BadRequestException, UnauthorizedException

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


def _configured() -> tuple[str, str, str]:
    if not all(
        (
            settings.GOOGLE_CLIENT_ID,
            settings.GOOGLE_CLIENT_SECRET,
            settings.GOOGLE_REDIRECT_URI,
        )
    ):
        raise BadRequestException(detail="Google OAuth is not configured")
    return (
        settings.GOOGLE_CLIENT_ID,
        settings.GOOGLE_CLIENT_SECRET,
        settings.GOOGLE_REDIRECT_URI,
    )


def authorization_url(state: str, nonce: str) -> str:
    from urllib.parse import urlencode

    client_id, _, redirect_uri = _configured()
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "access_type": "offline",
            "prompt": "select_account",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def exchange_code(code: str) -> dict[str, Any]:
    client_id, client_secret, redirect_uri = _configured()
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            token_data = response.json()
    except (httpx.HTTPError, ValueError):
        raise UnauthorizedException(detail="Unable to authenticate with Google")

    if not isinstance(token_data.get("id_token"), str):
        raise UnauthorizedException(detail="Google did not return an ID token")
    return token_data


def verify_id_token(id_token: str, expected_nonce: str) -> dict[str, Any]:
    client_id, _, _ = _configured()
    try:
        with httpx.Client(timeout=10.0) as client:
            discovery_response = client.get(GOOGLE_DISCOVERY_URL)
            discovery_response.raise_for_status()
            discovery = discovery_response.json()
            jwks_response = client.get(discovery["jwks_uri"])
            jwks_response.raise_for_status()
            keys = jwks_response.json()["keys"]

        header = jwt.get_unverified_header(id_token)
        key_data = next((key for key in keys if key.get("kid") == header.get("kid")), None)
        if key_data is None:
            raise UnauthorizedException(detail="Unable to verify Google identity")

        claims = jwt.decode(
            id_token,
            jwk.construct(key_data),
            algorithms=["RS256"],
            audience=client_id,
            issuer="https://accounts.google.com",
        )
    except (httpx.HTTPError, KeyError, ValueError, JWTError):
        raise UnauthorizedException(detail="Unable to verify Google identity")

    if claims.get("nonce") != expected_nonce:
        raise UnauthorizedException(detail="Invalid Google OAuth nonce")
    if claims.get("email_verified") is not True:
        raise UnauthorizedException(detail="Google email is not verified")
    if not isinstance(claims.get("email"), str) or not claims["email"]:
        raise UnauthorizedException(detail="Google account has no email")
    return claims

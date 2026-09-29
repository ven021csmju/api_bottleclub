from __future__ import annotations

import logging
from typing import Any

import httpx
from jose import JWTError, jwk, jwt

from app.config.settings import settings
from app.shared.exceptions import BadRequestException, UnauthorizedException

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
logger = logging.getLogger(__name__)


def _safe_exception_message(
    exc: Exception,
    extra_sensitive: tuple[str, ...] = (),
) -> str:
    message = str(exc)
    for sensitive in (
        settings.GOOGLE_CLIENT_ID,
        settings.GOOGLE_CLIENT_SECRET,
        *extra_sensitive,
    ):
        if sensitive:
            message = message.replace(sensitive, "[REDACTED]")
    return message[:300]


def _log_debug_failure(
    stage: str,
    exc: Exception,
    extra_sensitive: tuple[str, ...] = (),
) -> None:
    logger.debug(
        "Google OAuth debug failure: stage=%s exception_type=%s message=%s",
        stage,
        type(exc).__name__,
        _safe_exception_message(exc, extra_sensitive),
    )


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
            logger.debug(
                "Google OAuth token endpoint response: status=%s",
                response.status_code,
            )
            response.raise_for_status()
            token_data = response.json()
            if not isinstance(token_data, dict):
                logger.debug(
                    "Google OAuth token response has unexpected type: type=%s",
                    type(token_data).__name__,
                )
                raise UnauthorizedException(detail="Invalid Google token response")
            logger.debug(
                "Google OAuth token response keys: keys=%s",
                sorted(token_data.keys()),
            )
    except UnauthorizedException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        _log_debug_failure("exchange_code", exc, (code,))
        raise UnauthorizedException(detail="Unable to authenticate with Google")

    if not isinstance(token_data.get("id_token"), str):
        logger.debug("Google OAuth token response missing id_token: keys=%s", sorted(token_data.keys()))
        raise UnauthorizedException(detail="Google did not return an ID token")
    return token_data


def verify_id_token(id_token: str, expected_nonce: str) -> dict[str, Any]:
    client_id, _, _ = _configured()
    try:
        with httpx.Client(timeout=10.0) as client:
            discovery_response = client.get(GOOGLE_DISCOVERY_URL)
            logger.debug(
                "Google OpenID discovery response: status=%s",
                discovery_response.status_code,
            )
            discovery_response.raise_for_status()
            discovery = discovery_response.json()
            jwks_response = client.get(discovery["jwks_uri"])
            logger.debug(
                "Google JWKS response: status=%s",
                jwks_response.status_code,
            )
            jwks_response.raise_for_status()
            keys = jwks_response.json()["keys"]

        header = jwt.get_unverified_header(id_token)
        key_data = next((key for key in keys if key.get("kid") == header.get("kid")), None)
        logger.debug(
            "Google JWKS key selection: key_count=%s kid_present=%s key_matched=%s",
            len(keys),
            bool(header.get("kid")),
            key_data is not None,
        )
        if key_data is None:
            raise UnauthorizedException(detail="Unable to verify Google identity")

        claims = jwt.decode(
            id_token,
            jwk.construct(key_data),
            algorithms=["RS256"],
            audience=client_id,
            issuer="https://accounts.google.com",
        )
    except UnauthorizedException:
        raise
    except (httpx.HTTPError, KeyError, ValueError, JWTError) as exc:
        _log_debug_failure("verify_id_token", exc, (id_token, expected_nonce))
        raise UnauthorizedException(detail="Unable to verify Google identity")

    if claims.get("nonce") != expected_nonce:
        logger.debug("Google ID token claim validation failed: claim=nonce")
        raise UnauthorizedException(detail="Invalid Google OAuth nonce")
    if claims.get("email_verified") is not True:
        logger.debug("Google ID token claim validation failed: claim=email_verified")
        raise UnauthorizedException(detail="Google email is not verified")
    if not isinstance(claims.get("email"), str) or not claims["email"]:
        logger.debug("Google ID token claim validation failed: claim=email")
        raise UnauthorizedException(detail="Google account has no email")
    return claims

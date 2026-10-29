"""The refresh token in an HttpOnly cookie (Phase 45).

Opt-in per request: ``X-Auth-Mode: cookie`` at login, refresh and
change-password puts the refresh token in the ``__Host-bc_refresh`` cookie
(HttpOnly, Secure, SameSite=Strict, Path=/, no Domain) instead of the body.
Without the header the body carries it as before.
"""
from fastapi import Request, Response

from app.config.settings import settings

from .schemas import TokenResponse

REFRESH_COOKIE = "__Host-bc_refresh"
AUTH_MODE_HEADER = "X-Auth-Mode"


def cookie_mode(request: Request) -> bool:
    return request.headers.get(AUTH_MODE_HEADER, "").strip().lower() == "cookie"


def answer(request: Request, response: Response, tokens: TokenResponse) -> TokenResponse:
    """In cookie mode the refresh token goes in the cookie and not in the body."""
    if not cookie_mode(request):
        return tokens
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=tokens.refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return tokens.model_copy(update={"refresh_token": None})

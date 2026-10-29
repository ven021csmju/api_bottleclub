"""The refresh token in an HttpOnly cookie (Phase 45).

Opt-in per request: ``X-Auth-Mode: cookie`` at login, refresh and
change-password puts the refresh token in the ``__Host-bc_refresh`` cookie
(HttpOnly, Secure, SameSite=Strict, Path=/, no Domain) instead of the body.
Without the header the body carries it as before.

Over plain http outside production (a web on http://localhost) the cookie is
``bc_refresh``, same attributes: a browser keeps a Secure cookie from
http://localhost but refuses a ``__Host-`` one there (Chromium:
InvalidPrefix). Production always uses ``__Host-bc_refresh``.

A route that reads the cookie (refresh, logout) does so only for a request
that sends ``X-Auth-Mode: cookie`` from an origin of AUTH_COOKIE_ORIGINS;
any other is 403 CSRF_REJECTED. SameSite=Strict already keeps the cookie off
other sites' requests; this keeps it off the other origins of the same site
(another subdomain).
"""
from fastapi import Request, Response

from app.config.settings import settings
from app.shared.exceptions import ForbiddenException, UnauthorizedException

from .schemas import TokenResponse

REFRESH_COOKIE = "__Host-bc_refresh"
#: Over plain http outside production (see above).
LOCAL_REFRESH_COOKIE = "bc_refresh"
AUTH_MODE_HEADER = "X-Auth-Mode"


def cookie_name(request: Request) -> str:
    if request.url.scheme == "https" or settings.ENVIRONMENT.strip().lower() == "production":
        return REFRESH_COOKIE
    return LOCAL_REFRESH_COOKIE


def cookie_mode(request: Request) -> bool:
    return request.headers.get(AUTH_MODE_HEADER, "").strip().lower() == "cookie"


def answer(request: Request, response: Response, tokens: TokenResponse) -> TokenResponse:
    """In cookie mode the refresh token goes in the cookie and not in the body."""
    if not cookie_mode(request):
        return tokens
    response.set_cookie(
        key=cookie_name(request),
        value=tokens.refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return tokens.model_copy(update={"refresh_token": None})


def clear(request: Request, response: Response) -> None:
    """Delete the cookie (Max-Age=0). A __Host- cookie is deleted only with
    the attributes it was set with."""
    response.delete_cookie(cookie_name(request), path="/", secure=True, httponly=True, samesite="strict")


def ensure_cookie_request(request: Request) -> None:
    origin = request.headers.get("Origin", "")
    if not cookie_mode(request) or origin not in settings.auth_cookie_origins:
        raise ForbiddenException(
            detail=f"The refresh cookie is read only with {AUTH_MODE_HEADER}: cookie from an allowed origin",
            code="CSRF_REJECTED",
        )


def refresh_token_from_cookie(request: Request) -> str:
    """The refresh token of the cookie, for a request allowed to read it."""
    ensure_cookie_request(request)
    raw = request.cookies.get(cookie_name(request))
    if not raw:
        raise UnauthorizedException(
            detail="No refresh token: send it in the body, or log in with X-Auth-Mode: cookie",
            code="REFRESH_TOKEN_MISSING",
        )
    return raw

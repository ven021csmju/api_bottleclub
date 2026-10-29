"""The refresh token in an HttpOnly cookie (Phase 45).

Opt-in per request: ``X-Auth-Mode: cookie`` at login, refresh and
change-password puts the refresh token in a cookie (HttpOnly, Secure,
SameSite=Strict, Path=/, no Domain) instead of the body. Without the header
the body carries it as before.

One cookie per web (Phase 45b): the cookie belongs to the API's host, so
every web of the same browser would send the same one, and a login in the
admin web would become the POS tab's session at its next refresh. Its name
is therefore that of the request's Origin: ``__Host-bc_refresh_<id>``, ``id``
the first 8 hex of sha256(origin). Set, read and deleted by that name only.

Every cookie-mode request (and any request that would read the cookie) must
come from an origin of AUTH_COOKIE_ORIGINS, checked before anything is done;
any other is 403 CSRF_REJECTED. SameSite=Strict already keeps the cookie off
other sites' requests; this keeps it off the other origins of the same site
(another subdomain).

Over plain http outside production (a web on http://localhost) the prefix is
``bc_refresh_``, same attributes: a browser keeps a Secure cookie from
http://localhost but refuses a ``__Host-`` one there (Chromium:
InvalidPrefix). Production always uses ``__Host-``.
"""
import hashlib

from fastapi import Request, Response

from app.config.settings import settings
from app.shared.exceptions import ForbiddenException, UnauthorizedException

from .schemas import TokenResponse

REFRESH_COOKIE = "__Host-bc_refresh"
#: Over plain http outside production (see above).
LOCAL_REFRESH_COOKIE = "bc_refresh"
AUTH_MODE_HEADER = "X-Auth-Mode"


def cookie_mode(request: Request) -> bool:
    return request.headers.get(AUTH_MODE_HEADER, "").strip().lower() == "cookie"


def allowed_origin(request: Request) -> str | None:
    """The request's Origin when it may use the cookie, else None."""
    origin = request.headers.get("Origin", "")
    return origin if origin in settings.auth_cookie_origins else None


def ensure_cookie_request(request: Request) -> None:
    if not cookie_mode(request) or allowed_origin(request) is None:
        raise ForbiddenException(
            detail=f"The refresh cookie is used only with {AUTH_MODE_HEADER}: cookie from an allowed origin",
            code="CSRF_REJECTED",
        )


def cookie_name(request: Request, origin: str) -> str:
    """The cookie of ``origin``: one per web."""
    production = settings.ENVIRONMENT.strip().lower() == "production"
    prefix = REFRESH_COOKIE if request.url.scheme == "https" or production else LOCAL_REFRESH_COOKIE
    return f"{prefix}_{hashlib.sha256(origin.encode()).hexdigest()[:8]}"


def answer(request: Request, response: Response, tokens: TokenResponse) -> TokenResponse:
    """In cookie mode (the origin already checked) the refresh token goes in
    the origin's cookie and not in the body."""
    if not cookie_mode(request):
        return tokens
    response.set_cookie(
        key=cookie_name(request, allowed_origin(request)),
        value=tokens.refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return tokens.model_copy(update={"refresh_token": None})


def clear(request: Request, response: Response) -> None:
    """Delete the cookie of the request's origin (Max-Age=0), if it may have
    one. A __Host- cookie is deleted only with the attributes it was set with."""
    origin = allowed_origin(request)
    if origin is not None:
        response.delete_cookie(
            cookie_name(request, origin), path="/", secure=True, httponly=True, samesite="strict"
        )


def refresh_token_from_cookie(request: Request) -> str:
    """The refresh token of the origin's cookie, for a request allowed to read it."""
    ensure_cookie_request(request)
    raw = request.cookies.get(cookie_name(request, allowed_origin(request)))
    if not raw:
        raise UnauthorizedException(
            detail="No refresh token: send it in the body, or log in with X-Auth-Mode: cookie",
            code="REFRESH_TOKEN_MISSING",
        )
    return raw

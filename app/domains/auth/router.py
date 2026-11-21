import asyncio
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config.settings import settings
from app.db.session import get_db
from app.middleware.auth import get_authenticated_user, get_current_user
from app.middleware.rate_limit import limiter
from app.db.models import User
from app.shared.exceptions import ForbiddenException, UnauthorizedException

from .schemas import (
    ChangePasswordRequest,
    CustomerTokenResponse,
    ExchangeRequest,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserProfileResponse,
)
from . import login_guard
from .cookie import answer, clear, cookie_mode, cookie_name, ensure_cookie_request, refresh_token_from_cookie
from .service import AuthService
from .google import authorization_url, exchange_code, verify_id_token
from . import customer_login, line
from app.shared.exceptions import AppException, BadRequestException
from app.shared.security import create_customer_access_token

router = APIRouter()
logger = logging.getLogger(__name__)
#: How a slowed login waits (replaced in tests).
_wait = asyncio.sleep


@router.post("/register", response_model=RegisterResponse, status_code=201)
@limiter.limit(settings.RATE_LIMIT_REGISTER)
def register(
    request: Request,
    body: RegisterRequest,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    if not settings.registration_enabled:
        raise ForbiddenException(detail="Registration is disabled", code="REGISTRATION_DISABLED")
    return AuthService.register(db, body)

GOOGLE_STATE_COOKIE = "google_oauth_state"
GOOGLE_NONCE_COOKIE = "google_oauth_nonce"


def _secure_cookie() -> bool:
    return settings.ENVIRONMENT.lower() in {"production", "staging"}


@router.get("/google", include_in_schema=True, response_class=RedirectResponse, status_code=302,
            responses={302: {"description": "Redirect to Google's sign-in page (sets the state and nonce cookies)"}})
def google_login() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    response = RedirectResponse(authorization_url(state, nonce), status_code=302)
    for name, value in ((GOOGLE_STATE_COOKIE, state), (GOOGLE_NONCE_COOKIE, nonce)):
        response.set_cookie(
            key=name,
            value=value,
            httponly=True,
            secure=_secure_cookie(),
            samesite="lax",
            max_age=600,
            path="/",
        )
    logger.info("GOOGLE LOGIN stage=cookies_set state=True nonce=True")
    return response


@router.get("/google/callback", response_model=TokenResponse)
def google_callback(
    request: Request,
    http_response: Response,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
) -> TokenResponse:
    logger.info(
        "GOOGLE CALLBACK stage=start has_code=%s has_state=%s has_error=%s",
        bool(code),
        bool(state),
        bool(error),
    )
    if error or not code or not state:
        raise UnauthorizedException(detail="Google authentication was cancelled or failed")
    expected_state = request.cookies.get(GOOGLE_STATE_COOKIE)
    expected_nonce = request.cookies.get(GOOGLE_NONCE_COOKIE)
    state_match = (
        bool(state)
        and bool(expected_state)
        and secrets.compare_digest(state, expected_state)
    )
    logger.info(
        "GOOGLE CALLBACK stage=cookies state_present=%s nonce_present=%s state_match=%s",
        bool(expected_state),
        bool(expected_nonce),
        state_match,
    )
    if not expected_state or not expected_nonce or not state_match:
        raise UnauthorizedException(detail="Invalid Google OAuth state")

    logger.info("GOOGLE CALLBACK stage=exchange_code start")
    token_data = exchange_code(code)
    logger.info("GOOGLE CALLBACK stage=exchange_code success")
    logger.info("GOOGLE CALLBACK stage=verify_id_token start")
    claims = verify_id_token(token_data["id_token"], expected_nonce)
    logger.info("GOOGLE CALLBACK stage=verify_id_token success")
    logger.info("GOOGLE CALLBACK stage=login_with_google start")
    token_response = AuthService.login_with_google(
        db=db,
        claims=claims,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("User-Agent", ""),
        request_id=getattr(request.state, "request_id", ""),
    )
    logger.info("GOOGLE CALLBACK stage=login_with_google success")
    http_response.delete_cookie(GOOGLE_STATE_COOKIE)
    http_response.delete_cookie(GOOGLE_NONCE_COOKIE)
    return token_response


LINE_STATE_COOKIE = "line_oauth_state"
LINE_NONCE_COOKIE = "line_oauth_nonce"
LINE_RETURN_COOKIE = "line_oauth_return"
#: The LINE cookies are sent to the callback only.
LINE_COOKIE_PATH = "/api/v1/auth/line"


def _return_url(url: str, **params: str) -> str:
    from urllib.parse import urlencode

    return f"{url}?{urlencode(params)}"


@router.get("/line", response_class=RedirectResponse, status_code=302,
            responses={302: {"description": "Redirect to LINE's sign-in page (sets the state, nonce and return cookies)"},
                       400: {"description": "LINE Login is not configured, or return_to is not in FRONTEND_URLS"}})
@limiter.limit(settings.RATE_LIMIT_SOCIAL_LOGIN)
def line_login(
    request: Request,
    return_to: str | None = Query(None, description="One of FRONTEND_URLS (default: the first)"),
) -> RedirectResponse:
    """Customer sign-in with LINE. The callback sends the browser back to
    ``return_to`` with ``?code=<one-time code>`` (POST /auth/exchange) or
    ``?error=<reason>``; never a token in a URL."""
    line.ensure_configured()
    allowed = settings.frontend_urls
    target = return_to.strip() if return_to else allowed[0]
    if target not in allowed:
        raise BadRequestException(detail="return_to is not an allowed frontend URL", code="RETURN_TO_NOT_ALLOWED")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    response = RedirectResponse(line.authorization_url(state, nonce), status_code=302)
    for name, value in ((LINE_STATE_COOKIE, state), (LINE_NONCE_COOKIE, nonce), (LINE_RETURN_COOKIE, target)):
        response.set_cookie(
            key=name, value=value, httponly=True, secure=_secure_cookie(),
            samesite="lax", max_age=600, path=LINE_COOKIE_PATH,
        )
    return response


@router.get("/line/callback", response_class=RedirectResponse, status_code=302,
            responses={302: {"description": "Back to the frontend with ?code= (one-time, 60 s) or ?error="},
                       401: {"description": "No valid sign-in in progress (state/return cookie)"}})
@limiter.limit(settings.RATE_LIMIT_SOCIAL_LOGIN)
def line_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    line.ensure_configured()
    target = request.cookies.get(LINE_RETURN_COOKIE)
    expected_state = request.cookies.get(LINE_STATE_COOKIE)
    expected_nonce = request.cookies.get(LINE_NONCE_COOKIE)
    if not target or target not in settings.frontend_urls:
        raise UnauthorizedException(detail="No LINE sign-in in progress", code="LINE_STATE_INVALID")
    state_ok = bool(state and expected_state and expected_nonce and secrets.compare_digest(state, expected_state))

    if error or not code:
        location = _return_url(target, error="line_login_cancelled")
    elif not state_ok:
        location = _return_url(target, error="line_state_invalid")
    else:
        try:
            tokens = line.exchange_code(code)
            claims = line.verify_id_token(tokens["id_token"], expected_nonce)
            account = customer_login.sign_in(db, "line", claims)
            location = _return_url(target, code=customer_login.issue_code(db, account))
        except AppException as exc:
            db.rollback()
            logger.info("LINE CALLBACK failed code=%s", exc.code)
            location = _return_url(target, error="line_login_failed")
    response = RedirectResponse(location, status_code=302)
    # No cache: the Location holds a one-time code.
    response.headers["Cache-Control"] = "no-store"
    for name in (LINE_STATE_COOKIE, LINE_NONCE_COOKIE, LINE_RETURN_COOKIE):
        response.delete_cookie(name, path=LINE_COOKIE_PATH, secure=_secure_cookie(), httponly=True, samesite="lax")
    return response


@router.post("/exchange", response_model=CustomerTokenResponse,
             responses={401: {"description": "INVALID_EXCHANGE_CODE: unknown, used or expired"}})
@limiter.limit(settings.RATE_LIMIT_AUTH_EXCHANGE)
def exchange(request: Request, body: ExchangeRequest, db: Session = Depends(get_db)) -> CustomerTokenResponse:
    """A social login's one-time code (used up here) for a customer access token."""
    account = customer_login.redeem_code(db, body.code)
    return CustomerTokenResponse(
        access_token=create_customer_access_token(account.id, account.organization_id),
        expires_in=settings.CUSTOMER_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login", response_model=TokenResponse, response_model_exclude_none=True)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    if cookie_mode(request):
        ensure_cookie_request(request)  # before the login: the origin names the cookie
    ip_address = request.client.host if request.client else ""
    user_agent = request.headers.get("User-Agent", "")
    # Many wrong passwords for this username from anywhere: a slower answer,
    # never a lock (login_guard). Awaited, so a waiting login holds no thread.
    delay = await run_in_threadpool(login_guard.login_delay, db, body.username, datetime.now(timezone.utc))
    if delay:
        await _wait(delay)
    tokens = await run_in_threadpool(
        AuthService.login,
        db=db,
        username=body.username,
        password=body.password,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=getattr(request.state, "request_id", ""),
    )
    return answer(request, response, tokens)


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True)
@limiter.limit(settings.RATE_LIMIT_REFRESH)
def refresh(
    request: Request,
    response: Response,
    body: RefreshTokenRequest | None = None,
    db: Session = Depends(get_db),
) -> TokenResponse:
    ip_address = request.client.host if request.client else ""
    raw = body.refresh_token if body else None
    if cookie_mode(request):
        ensure_cookie_request(request)
    return answer(request, response, AuthService.refresh_token(
        db=db,
        raw_refresh_token=raw or refresh_token_from_cookie(request),
        ip_address=ip_address,
    ))


@router.post("/change-password", response_model=TokenResponse, response_model_exclude_none=True)
@limiter.limit(settings.RATE_LIMIT_CHANGE_PASSWORD)
def change_password(
    request: Request,
    response: Response,
    body: ChangePasswordRequest,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> TokenResponse:
    if cookie_mode(request):
        ensure_cookie_request(request)
    return answer(request, response, AuthService.change_password(
        db=db,
        user=user,
        current_password=body.current_password,
        new_password=body.new_password,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("User-Agent", ""),
    ))


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    body: LogoutRequest | None = None,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> Response:
    raw = body.refresh_token if body else None
    if cookie_mode(request):
        ensure_cookie_request(request)
        if not raw:
            # The origin's cookie; no cookie: every token, as with no body.
            raw = request.cookies.get(cookie_name(request, request.headers["Origin"]))
    AuthService.logout(
        db=db,
        user_id=user.id,
        raw_refresh_token=raw,
        request_id=getattr(request.state, "request_id", ""),
    )
    response = Response(status_code=204)
    clear(request, response)  # in either mode: the origin's cookie, if it may have one
    return response


@router.get("/me", response_model=UserProfileResponse)
def get_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    return AuthService.get_profile(db=db, user_id=user.id)

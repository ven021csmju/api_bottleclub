import logging
import secrets

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.middleware.rate_limit import limiter
from app.db.models import User
from app.shared.exceptions import UnauthorizedException

from .schemas import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserProfileResponse,
)
from .service import AuthService
from .google import authorization_url, exchange_code, verify_id_token

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    return AuthService.register(db, body)

GOOGLE_STATE_COOKIE = "google_oauth_state"
GOOGLE_NONCE_COOKIE = "google_oauth_nonce"


def _secure_cookie() -> bool:
    return settings.ENVIRONMENT.lower() in {"production", "staging"}


@router.get("/google", include_in_schema=True)
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


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    ip_address = request.client.host if request.client else ""
    user_agent = request.headers.get("User-Agent", "")
    return AuthService.login(
        db=db,
        username=body.username,
        password=body.password,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=getattr(request.state, "request_id", ""),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_REFRESH)
def refresh(
    request: Request,
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    ip_address = request.client.host if request.client else ""
    return AuthService.refresh_token(
        db=db,
        raw_refresh_token=body.refresh_token,
        ip_address=ip_address,
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    token_hash: str = getattr(request.state, "refresh_token_hash", "")
    AuthService.logout(
        db=db,
        user_id=user.id,
        token_hash=token_hash,
        request_id=getattr(request.state, "request_id", ""),
    )
    return Response(status_code=204)


@router.get("/me", response_model=UserProfileResponse)
def get_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    return AuthService.get_profile(db=db, user_id=user.id)

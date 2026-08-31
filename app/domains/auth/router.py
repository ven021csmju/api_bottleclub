from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.middleware.rate_limit import limiter
from app.db.models import User

from .schemas import LoginRequest, RefreshTokenRequest, TokenResponse, UserProfileResponse
from .service import AuthService

router = APIRouter()


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
    AuthService.logout(db=db, user_id=user.id, token_hash=token_hash)
    return Response(status_code=204)


@router.get("/me", response_model=UserProfileResponse)
def get_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    return AuthService.get_profile(db=db, user_id=user.id)

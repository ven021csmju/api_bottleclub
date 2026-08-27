from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.db.models import User

from .schemas import LoginRequest, RefreshTokenRequest, TokenResponse, UserProfileResponse
from .service import AuthService

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
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
def refresh(
    body: RefreshTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    ip_address = request.client.host if request.client else ""
    return AuthService.refresh_token(
        db=db,
        raw_refresh_token=body.refresh_token,
        ip_address=ip_address,
    )


@router.post("/logout")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    token_hash: str = getattr(request.state, "refresh_token_hash", "")
    AuthService.logout(db=db, user_id=user.id, token_hash=token_hash)
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserProfileResponse)
def get_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    return AuthService.get_profile(db=db, user_id=user.id)

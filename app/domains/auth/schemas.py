from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.shared.security import MAX_PASSWORD_BYTES


def _fits_bcrypt(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes (UTF-8)")
    return value


#: A password bcrypt can hash: longer → 422, not 500.
BcryptPassword = Annotated[str, AfterValidator(_fits_bcrypt)]


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: BcryptPassword = Field(min_length=8, max_length=MAX_PASSWORD_BYTES)
    display_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    organization_id: int | None = None


class RegisterResponse(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    phone: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    #: Left out in cookie mode (X-Auth-Mode: cookie): it is in the cookie.
    refresh_token: str | None = None
    #: True: every route but POST /auth/change-password (and logout) answers
    #: 403 PASSWORD_CHANGE_REQUIRED until the password is changed.
    password_change_required: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: BcryptPassword = Field(min_length=12)


class RefreshTokenRequest(BaseModel):
    #: Left out: the one of the cookie (X-Auth-Mode: cookie, Phase 45).
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    #: The refresh token to revoke. Left out: the cookie's with X-Auth-Mode:
    #: cookie (Phase 45), else (or with no cookie) every refresh token of the user.
    refresh_token: str | None = None


class TokenPayload(BaseModel):
    user_id: int
    organization_id: int
    permissions: list[str]
    branches: list[int]
    exp: int
    iat: int
    sub: str


class UserProfileResponse(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    organization_id: int
    is_superadmin: bool
    permissions: list[str]
    branches: list[int]

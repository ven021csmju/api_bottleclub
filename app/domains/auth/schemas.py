from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
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
    refresh_token: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


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

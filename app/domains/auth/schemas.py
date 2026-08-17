from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


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

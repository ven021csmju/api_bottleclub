import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    display_name: str
    phone: str | None = None
    branch_ids: list[int] = []


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    display_name: str | None = None
    phone: str | None = None
    status: str | None = None
    branch_ids: list[int] | None = None


class UserRoleAssign(BaseModel):
    role_id: int
    branch_id: int | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    phone: str | None
    status: str
    is_superadmin: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
    page: int
    per_page: int

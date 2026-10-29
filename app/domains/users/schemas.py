import datetime

from typing import Any

from pydantic import BaseModel, EmailStr, Field, model_validator

#: Fields a client may send but must not set; 422 instead of silently ignoring them.
REJECTED_FIELDS = {
    "branch_ids": "branch_ids was removed: a branch is part of a role assignment, "
    "give roles: [{role_id, branch_id}] on POST /users/ or use POST/DELETE /users/{id}/roles",
    # Display only; no permission check reads it (app/domains/roles/access.py).
    "is_superadmin": "is_superadmin is read-only: Superadmin authority is the Superadmin role, "
    "assigned with POST /users/{id}/roles",
    "password": "password is set by the server: POST /users/ answers a temporary password once, "
    "POST /users/{id}/reset-password gives a new one; the user then sets their own",
}


class _RejectFields(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _reject_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for name, message in REJECTED_FIELDS.items():
                if name in data:
                    raise ValueError(message)
        return data


class UserRoleAssign(BaseModel):
    role_id: int
    branch_id: int | None = None

    model_config = {"from_attributes": True}


class UserCreate(_RejectFields):
    username: str
    email: EmailStr
    display_name: str
    phone: str | None = None
    roles: list[UserRoleAssign] = []


class UserUpdate(_RejectFields):
    email: EmailStr | None = None
    display_name: str | None = None
    phone: str | None = None
    status: str | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    phone: str | None
    status: str
    is_superadmin: bool
    must_change_password: bool
    temp_password_expires_at: datetime.datetime | None
    roles: list[UserRoleAssign] = Field(default=[], validation_alias="user_roles")
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class UserCreatedResponse(UserResponse):
    #: Shown once; the user must change it at the first login.
    temporary_password: str


class LoginUnlockResponse(BaseModel):
    user_id: int
    #: Every lock of the user's logins (any IP) and the slow-down end now (Phase 48-0).
    unlocked_at: datetime.datetime


class PasswordResetResponse(BaseModel):
    user_id: int
    #: Shown once; the user must change it at the next login.
    temporary_password: str
    temp_password_expires_at: datetime.datetime


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
    page: int
    per_page: int

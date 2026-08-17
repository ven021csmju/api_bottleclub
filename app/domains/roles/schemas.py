import datetime

from pydantic import BaseModel


class PermissionResponse(BaseModel):
    id: int
    code: str
    module: str
    description: str | None

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permission_ids: list[int] | None = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str | None
    is_system: bool
    permissions: list[PermissionResponse]
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class RoleListResponse(BaseModel):
    roles: list[RoleResponse]
    total: int
    page: int
    per_page: int

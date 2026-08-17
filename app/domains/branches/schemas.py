import datetime

from pydantic import BaseModel


class BranchCreate(BaseModel):
    name: str
    code: str
    phone: str | None = None
    address: str | None = None


class BranchUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None
    is_active: bool | None = None


class BranchResponse(BaseModel):
    id: int
    organization_id: int
    name: str
    code: str
    phone: str | None
    address: str | None
    is_active: bool
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class BranchListResponse(BaseModel):
    branches: list[BranchResponse]
    total: int

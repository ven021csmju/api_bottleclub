from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RegisterCreate(BaseModel):
    branch_id: int
    name: str = Field(..., min_length=1, max_length=100)


class RegisterUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    # False closes the register: no new shift can open on it.
    is_active: Optional[bool] = None


class RegisterResponse(BaseModel):
    id: int
    branch_id: int
    name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RegisterListResponse(BaseModel):
    registers: list[RegisterResponse]
    total: int

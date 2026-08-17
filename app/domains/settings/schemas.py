from typing import Optional

from pydantic import BaseModel


class SettingResponse(BaseModel):
    key: str
    value: str
    value_type: str
    description: Optional[str] = None
    branch_id: Optional[int] = None

    model_config = {"from_attributes": True}


class SettingUpdate(BaseModel):
    value: str
    value_type: Optional[str] = None


class SettingListResponse(BaseModel):
    settings: list[SettingResponse]
    total: int

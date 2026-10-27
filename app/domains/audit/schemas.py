from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.shared.clock import StoreDateTime


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    before_data: Optional[dict[str, Any]] = None
    after_data: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int
    page: int
    per_page: int


class AuditLogFilter(BaseModel):
    user_id: Optional[int] = None
    action: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    date_from: Optional[StoreDateTime] = None
    date_to: Optional[StoreDateTime] = None

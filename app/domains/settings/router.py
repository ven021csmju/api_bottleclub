from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.database import get_db
from app.domains.settings.schemas import (
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from app.domains.settings.service import SettingService
from app.middleware.auth import require_permission
from database.models import User

router = APIRouter()


@router.get("/", response_model=SettingListResponse)
def list_settings(
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.read")),
) -> SettingListResponse:
    settings = SettingService.list_settings(
        db, user.organization_id, branch_id
    )
    return SettingListResponse(settings=settings, total=len(settings))


@router.get("/{key}", response_model=SettingResponse)
def get_setting(
    key: str,
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.read")),
) -> SettingResponse:
    return SettingService.get_setting(db, user.organization_id, key, branch_id)


@router.put("/{key}", response_model=SettingResponse)
def update_setting(
    key: str,
    data: SettingUpdate,
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.update")),
) -> SettingResponse:
    return SettingService.update_setting(
        db,
        user.organization_id,
        key,
        data.value,
        data.value_type,
        branch_id,
    )

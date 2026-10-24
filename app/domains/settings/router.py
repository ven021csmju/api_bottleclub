from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.settings.schemas import (
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from app.domains.settings.service import SettingService
from app.middleware.access import Access
from app.middleware.auth import get_access, require_permission
from app.shared.exceptions import ForbiddenException
from app.db.models import User

router = APIRouter()


@router.get("/", response_model=SettingListResponse)
def list_settings(
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.read", scope="any")),
    access: Access = Depends(get_access),
) -> SettingListResponse:
    if branch_id is not None:
        access.ensure_at("settings.read", branch_id, "Branch")
    settings = SettingService.list_settings(
        db, user.organization_id, branch_id
    )
    return SettingListResponse(settings=settings, total=len(settings))


@router.get("/{key}", response_model=SettingResponse)
def get_setting(
    key: str,
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.read", scope="any")),
    access: Access = Depends(get_access),
) -> SettingResponse:
    if branch_id is not None:
        access.ensure_at("settings.read", branch_id, "Branch")
    return SettingService.get_setting(db, user.organization_id, key, branch_id)


@router.put("/{key}", response_model=SettingResponse)
def update_setting(
    key: str,
    data: SettingUpdate,
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.update", scope="any")),
    access: Access = Depends(get_access),
) -> SettingResponse:
    if branch_id is not None:
        access.ensure_at("settings.update", branch_id, "Branch")
    elif not access.superadmin:
        # Organization-wide settings apply to every branch.
        raise ForbiddenException(detail="Only a Superadmin can change organization settings")
    return SettingService.update_setting(
        db,
        user.organization_id,
        key,
        data.value,
        data.value_type,
        branch_id,
    )

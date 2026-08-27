from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.database import get_db
from app.domains.audit.schemas import (
    AuditLogListResponse,
    AuditLogResponse,
)
from app.domains.audit.service import AuditService
from app.middleware.auth import require_permission
from database.models import User
from app.shared.pagination import PaginationParams

router = APIRouter()


@router.get("/", response_model=AuditLogListResponse)
def list_audit_logs(
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("audit.read")),
) -> AuditLogListResponse:
    logs, total = AuditService.list_audit_logs(
        db,
        user.organization_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        page=pagination.page,
        per_page=pagination.per_page,
    )
    return AuditLogListResponse(
        logs=logs,
        total=total,
        page=pagination.page,
        per_page=pagination.per_page,
    )


@router.get("/{log_id}", response_model=AuditLogResponse)
def get_audit_log(
    log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("audit.read")),
) -> AuditLogResponse:
    result = AuditService.get_audit_log(db, user.organization_id, log_id)
    return AuditLogResponse(**result)

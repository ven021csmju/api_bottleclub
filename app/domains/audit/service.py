from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.audit.schemas import AuditLogResponse
from app.models import AuditLog, User
from app.shared.exceptions import NotFoundException
from app.shared.pagination import paginate


class AuditService:
    @staticmethod
    def list_audit_logs(
        db: Session,
        organization_id: int,
        user_id: int | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[AuditLogResponse], int]:
        stmt = (
            select(AuditLog, User.display_name.label("user_name"))
            .outerjoin(User, AuditLog.user_id == User.id)
            .where(AuditLog.organization_id == organization_id)
        )

        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if entity_type is not None:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if date_from:
            stmt = stmt.where(AuditLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(AuditLog.created_at <= date_to)

        stmt = stmt.order_by(AuditLog.id.desc())

        total_query = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(total_query) or 0

        rows = db.execute(stmt.offset((page - 1) * per_page).limit(per_page)).all()

        logs = [
            AuditLogResponse(
                id=log.id,
                user_id=log.user_id,
                user_name=user_name,
                action=log.action,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                before_data=log.before_data,
                after_data=log.after_data,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log, user_name in rows
        ]
        return logs, total

    @staticmethod
    def get_audit_log(db: Session, organization_id: int, log_id: int) -> AuditLogResponse:
        row = db.execute(
            select(AuditLog, User.display_name.label("user_name"))
            .outerjoin(User, AuditLog.user_id == User.id)
            .where(
                AuditLog.id == log_id,
                AuditLog.organization_id == organization_id,
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException(detail="Audit log not found")

        log, user_name = row
        return AuditLogResponse(
            id=log.id,
            user_id=log.user_id,
            user_name=user_name,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            before_data=log.before_data,
            after_data=log.after_data,
            ip_address=log.ip_address,
            created_at=log.created_at,
        )

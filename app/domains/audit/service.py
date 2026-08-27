from datetime import datetime

from sqlalchemy.orm import Session

from app.domains.audit.schemas import AuditLogResponse
from app.db.repositories.audit import AuditRepository
from app.shared.exceptions import NotFoundException


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
        rows, total = AuditRepository.list_audit_logs(
            db, organization_id, user_id, action, entity_type,
            entity_id, date_from, date_to, page, per_page,
        )

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
        row = AuditRepository.get_audit_log(db, organization_id, log_id)
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
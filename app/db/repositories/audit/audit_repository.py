from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, User


class AuditRepository:
    @staticmethod
    def list_audit_logs(
        db: Session,
        organization_id: int,
        user_id: int | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        date_from=None,
        date_to=None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[tuple], int]:
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

        total = db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        rows = db.execute(stmt.offset((page - 1) * per_page).limit(per_page)).all()
        return list(rows), total

    @staticmethod
    def get_audit_log(
        db: Session, organization_id: int, log_id: int
    ) -> tuple | None:
        return db.execute(
            select(AuditLog, User.display_name.label("user_name"))
            .outerjoin(User, AuditLog.user_id == User.id)
            .where(
                AuditLog.id == log_id,
                AuditLog.organization_id == organization_id,
            )
        ).one_or_none()

    @staticmethod
    def add_audit_log(db: Session, log: AuditLog) -> None:
        db.add(log)
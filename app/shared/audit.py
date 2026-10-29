from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.db.repositories.audit import AuditRepository


@dataclass
class AuditContext:
    user_id: int
    organization_id: int
    ip_address: str
    user_agent: str
    request_id: str


def log_audit(
    db: Session,
    ctx: AuditContext,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    at: Any = None,
) -> None:
    """``at``: the moment to record (a SQL expression such as ``func.clock_timestamp()``);
    None: the column's default (the transaction's start)."""
    audit_log = AuditLog(
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=before_data,
        after_data=after_data,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
        metadata=metadata,
    )
    if at is not None:
        audit_log.created_at = at
    AuditRepository.add_audit_log(db, audit_log)

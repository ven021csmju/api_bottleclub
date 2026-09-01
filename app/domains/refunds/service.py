from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Refund
from app.db.repositories.refunds import RefundRepository
from app.shared.audit import AuditContext, log_audit
from app.shared.exceptions import (
    BadRequestException,
    InvalidOrderStateException,
    NotFoundException,
)
from app.shared.ordering import generate_refund_number


class RefundService:
    @staticmethod
    def list_refunds(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        order_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> dict:
        items, total = RefundRepository.list_refunds(
            db, org_id, page, per_page, date_from, date_to, order_id, status
        )

        return {
            "refunds": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_refund(db: Session, refund_id: int) -> Refund:
        refund = RefundRepository.get_refund(db, refund_id)

        if not refund:
            raise NotFoundException(detail="Refund not found")
        return refund

    @staticmethod
    def create_refund(
        db: Session,
        org_id: int,
        user_id: int,
        audit: AuditContext,
        data: dict,
    ) -> Refund:
        order = RefundRepository.get_org_order(db, org_id, data["order_id"])
        if not order:
            raise NotFoundException(detail="Order not found")

        if order.grand_total is not None and data["refund_amount"] > order.grand_total:
            raise BadRequestException(
                detail="Refund amount exceeds order grand total"
            )

        refund_number = generate_refund_number(db)

        refund = Refund(
            order_id=order.id,
            refund_number=refund_number,
            refund_amount=data["refund_amount"],
            refund_method=data["refund_method"],
            status="pending",
            processed_by=user_id,
            external_reference=data.get("external_reference"),
            reason=data.get("reason"),
        )
        RefundRepository.add_refund(db, refund)

        log_audit(
            db=db,
            ctx=audit,
            action="REFUND.CREATE",
            entity_type="refund",
            entity_id=refund.id,
            after_data={
                "order_id": order.id,
                "refund_number": refund_number,
                "refund_amount": data["refund_amount"],
                "refund_method": data["refund_method"],
                "status": "pending",
            },
        )

        db.flush()
        db.commit()
        db.refresh(refund)
        return refund
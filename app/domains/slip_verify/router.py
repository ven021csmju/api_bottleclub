import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.repositories.slip_verify.slip_verify_repository import SlipVerifyRepository
from app.middleware.access import Access
from app.middleware.auth import get_access, get_audit_context, get_current_user
from app.db.models import User
from app.services import user_events
from app.shared.audit import AuditContext
from app.shared.exceptions import ForbiddenException, NotFoundException

from .schemas import (
    ErrorResponse,
    VerificationApproveRequest,
    VerificationDetailResponse,
    VerificationListResponse,
    VerificationModerationRequest,
    VerificationResponse,
)
from .service import SlipVerifyService
from app.middleware.auth import require_permission

logger = logging.getLogger(__name__)

router = APIRouter()

#: Statuses where the uploaded slip image was accepted into the system (a
#: Verification record was created for it). Everything else rejected the
#: upload before a record existed, so no ``slip_upload`` event is emitted.
_UPLOAD_ACCEPTED_STATUSES = {
    "ocr_failed",
    "verified",
    "review",
    "rejected",
    "amount_mismatch",
    "duplicate_reference",
    "receiver_mismatch",
}


#: Staff permission that may submit a slip for any order of the organization.
#: Without it a user may only submit for an order they own (``orders.user_id``).
UPLOAD_PERMISSION = "payments.create"


def _ensure_slip_access(db: Session, access: Access, order_id: int, code: str) -> None:
    """404 unless ``code`` is held at the branch of the slip's order."""
    branch_id = SlipVerifyRepository.get_org_order_branch(db, order_id, access.org_id)
    access.ensure_at(code, branch_id, "Verification")


def _ensure_verification_access(db: Session, access: Access, verification_id: int, code: str) -> None:
    verification = SlipVerifyService.get_org_verification(db, verification_id, access.org_id)
    if not verification:
        raise NotFoundException(detail="Verification not found")
    _ensure_slip_access(db, access, verification.order_id, code)


#: HTTP status per result status; everything else is 200.
_HTTP_STATUS = {
    "order_not_found": 404,
    "ocr_failed": 422,
    "order_already_paid": 400,
    "unsupported_media_type": 415,
}


# Sync on purpose: FastAPI runs it in the threadpool, so the blocking DB work,
# image decoding and OCR HTTP call never stall the event loop.
def _process_slip(
    request: Request,
    file: UploadFile,
    order_id: int,
    user: User,
    access: Access,
    db: Session,
) -> JSONResponse:
    # Same 403 whether the order is someone else's or does not exist, so
    # order ids cannot be probed.
    branch_id = SlipVerifyRepository.get_org_order_branch(db, order_id, user.organization_id)
    staff = branch_id is not None and access.can_at(UPLOAD_PERMISSION, branch_id)
    if not staff and not SlipVerifyRepository.is_order_owner(
        db, order_id, user.organization_id, user.id
    ):
        raise ForbiddenException(detail="Not allowed to submit a slip for this order")

    file_bytes = file.file.read()

    result = SlipVerifyService.verify_slip(
        db=db,
        user=user,
        order_id=order_id,
        file_bytes=file_bytes,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent", ""),
    )

    db.commit()

    status = result.get("status")
    status_code = _HTTP_STATUS.get(status, 200)
    if status in _UPLOAD_ACCEPTED_STATUSES:
        verification_id = None
        storage_key = None
        data = result.get("data")
        if isinstance(data, dict) and data.get("verification_id"):
            verification_id = data["verification_id"]
        latest = SlipVerifyService.list_verifications_by_order(db, order_id, limit=1)
        if latest:
            verification_id = verification_id or latest[0].id
            storage_key = latest[0].image_storage_key
        # Worker thread, no running loop: the sync helper; it never raises.
        user_events.publish_user_event_sync(
            "slip_upload",
            user.id,
            getattr(request.state, "request_id", ""),
            {
                "order_id": order_id,
                "verification_id": verification_id,
                "storage_key": storage_key,
                "status": status,
            },
        )
    if status == "verified":
        # The slip settled the order: same event as POS checkout.
        user_events.publish_user_event_sync(
            "purchase_completed",
            user.id,
            getattr(request.state, "request_id", ""),
            {"order_id": order_id, "amount_paid": str(result["data"]["amount"])},
        )

    return JSONResponse(status_code=status_code, content=result)


@router.post("/upload", response_model=None)
def upload_slip(
    request: Request,
    file: UploadFile = File(..., description="Slip image (JPEG, PNG, WebP, max 10MB)"),
    order_id: int = Form(..., description="Order ID to verify against"),
    user: User = Depends(get_current_user),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
):
    return _process_slip(request, file, order_id, user, access, db)


@router.post("/checkslip", response_model=None, deprecated=True)
def check_slip(
    request: Request,
    file: UploadFile = File(..., description="Slip image (JPEG, PNG, WebP, max 10MB)"),
    order_id: int = Form(..., description="Order ID to verify against"),
    user: User = Depends(get_current_user),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
):
    """Deprecated (Phase 40): the same as POST /upload, which replaces it.
    Answers carry ``Deprecation: true`` and a successor Link."""
    return _process_slip(request, file, order_id, user, access, db)


def _verification_detail(verification) -> dict:
    risk_score = verification.risk_score
    if isinstance(risk_score, dict):
        risk_score = risk_score.get("score", 0)
    return {
        "id": verification.id,
        "order_id": verification.order_id,
        "payment_id": verification.payment_id,
        "ocr_bank": verification.ocr_bank,
        "ocr_amount": float(verification.ocr_amount) if verification.ocr_amount else None,
        "ocr_reference": verification.ocr_reference,
        "ocr_date": verification.ocr_date,
        "ocr_sender_name": verification.ocr_sender_name,
        "ocr_receiver_name": verification.ocr_receiver_name,
        "ocr_receiver_account": verification.ocr_receiver_account,
        "image_sha256": verification.image_sha256,
        "status": verification.status,
        "risk_score": risk_score,
        "risk_signals": verification.risk_signals,
        "failure_reason": verification.failure_reason,
        "created_at": verification.created_at,
    }


@router.get("/list", response_model=VerificationListResponse)
def list_verifications(
    status: str | None = None,
    limit: int = 100,
    user: User = Depends(require_permission("slip_verification.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> VerificationListResponse:
    if limit < 1 or limit > 100:
        from app.shared.exceptions import BadRequestException
        raise BadRequestException(detail="limit must be between 1 and 100")
    items = SlipVerifyService.list_verifications(
        db, user.organization_id, status, limit, branches=access.branches("slip_verification.read")
    )
    return VerificationListResponse(
        items=[VerificationDetailResponse.model_validate(_verification_detail(item)) for item in items],
        total=len(items),
    )


@router.post("/{verification_id}/approve", response_model=VerificationDetailResponse)
def approve_verification(
    verification_id: int,
    body: VerificationApproveRequest,
    user: User = Depends(require_permission("slip_verification.approve", scope="any")),
    access: Access = Depends(get_access),
    audit: AuditContext = Depends(get_audit_context),
    db: Session = Depends(get_db),
) -> VerificationDetailResponse:
    _ensure_verification_access(db, access, verification_id, "slip_verification.approve")
    verification = SlipVerifyService.approve_verification(
        db,
        verification_id=verification_id,
        audit=audit,
        confirmed_amount=body.confirmed_amount,
        bank_reference=body.bank_reference,
        note=body.note,
    )
    return VerificationDetailResponse.model_validate(_verification_detail(verification))


@router.post("/{verification_id}/reject", response_model=VerificationDetailResponse)
def reject_verification(
    verification_id: int,
    body: VerificationModerationRequest | None = None,
    user: User = Depends(require_permission("slip_verification.reject", scope="any")),
    access: Access = Depends(get_access),
    audit: AuditContext = Depends(get_audit_context),
    db: Session = Depends(get_db),
) -> VerificationDetailResponse:
    _ensure_verification_access(db, access, verification_id, "slip_verification.reject")
    verification = SlipVerifyService.reject_verification(
        db,
        verification_id=verification_id,
        audit=audit,
        note=body.note if body else None,
    )
    return VerificationDetailResponse.model_validate(_verification_detail(verification))


@router.get("/{verification_id}")
def get_verification(
    verification_id: int,
    user: User = Depends(require_permission("slip_verification.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
):
    _ensure_verification_access(db, access, verification_id, "slip_verification.read")
    verification = SlipVerifyService.get_org_verification(
        db, verification_id, user.organization_id
    )
    return _verification_detail(verification)


@router.get("/order/{order_id}")
def list_verifications_by_order(
    order_id: int,
    user: User = Depends(require_permission("slip_verification.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
):
    _ensure_slip_access(db, access, order_id, "slip_verification.read")
    verifications = SlipVerifyService.list_org_verifications_by_order(
        db, order_id, user.organization_id
    )
    return [
        {
            "id": v.id,
            "order_id": v.order_id,
            "status": v.status,
            "risk_score": v.risk_score.get("score", 0) if isinstance(v.risk_score, dict) else v.risk_score,
            "ocr_amount": float(v.ocr_amount) if v.ocr_amount else None,
            "ocr_reference": v.ocr_reference,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in verifications
    ]

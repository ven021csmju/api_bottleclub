import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.db.models import User
from app.services import user_events

from .schemas import (
    ErrorResponse,
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
}


async def _process_slip(
    request: Request,
    file: UploadFile,
    order_id: int,
    user: User,
    db: Session,
) -> JSONResponse:
    file_bytes = await file.read()

    result = SlipVerifyService.verify_slip(
        db=db,
        user=user,
        order_id=order_id,
        file_bytes=file_bytes,
        filename=file.filename or "unknown.jpg",
        content_type=file.content_type or "",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent", ""),
    )

    db.commit()

    status_code = 200
    if result.get("status") in ("order_not_found",):
        status_code = 404
    elif result.get("status") in ("ocr_failed",):
        status_code = 422
    elif result.get("status") in ("order_already_paid",):
        status_code = 400

    status = result.get("status")
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
        # Async entry point (this endpoint runs in the event loop), so use the
        # awaitable helper; publish_user_event never raises.
        await user_events.publish_user_event(
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

    return JSONResponse(status_code=status_code, content=result)


@router.post("/upload", response_model=None)
async def upload_slip(
    request: Request,
    file: UploadFile = File(..., description="Slip image (JPEG, PNG, WebP, max 10MB)"),
    order_id: int = Form(..., description="Order ID to verify against"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await _process_slip(request, file, order_id, user, db)


@router.post("/checkslip", response_model=None)
async def check_slip(
    request: Request,
    file: UploadFile = File(..., description="Slip image (JPEG, PNG, WebP, max 10MB)"),
    order_id: int = Form(..., description="Order ID to verify against"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await _process_slip(request, file, order_id, user, db)


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
    user: User = Depends(require_permission("slip_verification.read")),
    db: Session = Depends(get_db),
) -> VerificationListResponse:
    if limit < 1 or limit > 100:
        from app.shared.exceptions import BadRequestException
        raise BadRequestException(detail="limit must be between 1 and 100")
    items = SlipVerifyService.list_verifications(db, user.organization_id, status, limit)
    return VerificationListResponse(
        items=[VerificationDetailResponse.model_validate(_verification_detail(item)) for item in items],
        total=len(items),
    )


@router.post("/{verification_id}/approve", response_model=VerificationDetailResponse)
def approve_verification(
    verification_id: int,
    body: VerificationModerationRequest | None = None,
    user: User = Depends(require_permission("slip_verification.approve")),
    db: Session = Depends(get_db),
) -> VerificationDetailResponse:
    verification = SlipVerifyService.moderate_verification(
        db,
        verification_id=verification_id,
        organization_id=user.organization_id,
        user_id=user.id,
        approve=True,
        note=body.note if body else None,
    )
    return VerificationDetailResponse.model_validate(_verification_detail(verification))


@router.post("/{verification_id}/reject", response_model=VerificationDetailResponse)
def reject_verification(
    verification_id: int,
    body: VerificationModerationRequest | None = None,
    user: User = Depends(require_permission("slip_verification.reject")),
    db: Session = Depends(get_db),
) -> VerificationDetailResponse:
    verification = SlipVerifyService.moderate_verification(
        db,
        verification_id=verification_id,
        organization_id=user.organization_id,
        user_id=user.id,
        approve=False,
        note=body.note if body else None,
    )
    return VerificationDetailResponse.model_validate(_verification_detail(verification))


@router.get("/{verification_id}")
def get_verification(
    verification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verification = SlipVerifyService.get_org_verification(
        db, verification_id, user.organization_id
    )
    if not verification:
        from app.shared.exceptions import NotFoundException
        raise NotFoundException(detail="Verification not found")

    return _verification_detail(verification)


@router.get("/order/{order_id}")
def list_verifications_by_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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

import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from database.database import get_db
from app.middleware.auth import get_current_user
from database.models import User

from .schemas import ErrorResponse, VerificationResponse
from .service import SlipVerifyService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", response_model=None)
async def upload_slip(
    request: Request,
    file: UploadFile = File(..., description="Slip image (JPEG, PNG, WebP, max 10MB)"),
    order_id: int = Form(..., description="Order ID to verify against"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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

    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content=result)


@router.get("/{verification_id}")
def get_verification(
    verification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verification = SlipVerifyService.get_verification(db, verification_id)
    if not verification:
        from app.shared.exceptions import NotFoundException
        raise NotFoundException(detail="Verification not found")

    return {
        "id": verification.id,
        "order_id": verification.order_id,
        "payment_id": verification.payment_id,
        "ocr_bank": verification.ocr_bank,
        "ocr_amount": float(verification.ocr_amount) if verification.ocr_amount else None,
        "ocr_reference": verification.ocr_reference,
        "ocr_date": str(verification.ocr_date) if verification.ocr_date else None,
        "ocr_sender_name": verification.ocr_sender_name,
        "ocr_receiver_name": verification.ocr_receiver_name,
        "ocr_receiver_account": verification.ocr_receiver_account,
        "image_sha256": verification.image_sha256,
        "status": verification.status,
        "risk_score": float(verification.risk_score),
        "risk_signals": verification.risk_signals,
        "failure_reason": verification.failure_reason,
        "created_at": verification.created_at.isoformat() if verification.created_at else None,
    }


@router.get("/order/{order_id}")
def list_verifications_by_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verifications = SlipVerifyService.list_verifications_by_order(db, order_id)
    return [
        {
            "id": v.id,
            "order_id": v.order_id,
            "status": v.status,
            "risk_score": float(v.risk_score),
            "ocr_amount": float(v.ocr_amount) if v.ocr_amount else None,
            "ocr_reference": v.ocr_reference,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in verifications
    ]

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field, StringConstraints


class OCRFieldSchema(BaseModel):
    raw: str
    value: Any
    confidence: float


class VerificationDataSchema(BaseModel):
    verification_id: int
    order_id: int
    amount: Decimal
    reference: str | None = None
    bank: str | None = None
    date: str | None = None
    time: str | None = None
    sender_name: str | None = None
    receiver_name: str | None = None
    risk_score: float
    verified_at: datetime | None = None


class VerificationResponse(BaseModel):
    success: bool
    status: str
    message: str
    data: VerificationDataSchema | None = None


class AmountMismatchData(BaseModel):
    expected_amount: Decimal
    detected_amount: Decimal | None = None
    risk_score: float


class AmountMismatchResponse(BaseModel):
    success: bool
    status: str
    message: str
    data: AmountMismatchData | None = None


class DuplicateData(BaseModel):
    existing_verification_id: int | None = None
    existing_order_id: int | None = None


class DuplicateResponse(BaseModel):
    success: bool
    status: str
    message: str
    data: DuplicateData | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    status: str
    message: str


class VerificationDetailResponse(BaseModel):
    id: int
    order_id: int
    payment_id: int | None = None
    ocr_bank: str | None = None
    ocr_amount: Decimal | None = None
    ocr_reference: str | None = None
    ocr_date: date | None = None
    ocr_sender_name: str | None = None
    ocr_receiver_name: str | None = None
    ocr_receiver_account: str | None = None
    image_sha256: str | None = None
    status: str
    risk_score: Decimal
    risk_signals: dict | None = None
    failure_reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VerificationModerationRequest(BaseModel):
    note: str | None = Field(None, max_length=1000)


class VerificationApproveRequest(BaseModel):
    """Manual approval: staff confirm the transfer in the bank app first."""

    confirmed_amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    bank_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class VerificationListResponse(BaseModel):
    items: list[VerificationDetailResponse]
    total: int


class VerificationDetailRead(VerificationDetailResponse):
    """GET /slip-verify/{id}: the same fields, amounts as JSON numbers (as it always answered)."""

    ocr_amount: float | None = None
    risk_score: float


class VerificationOfOrder(BaseModel):
    """One verification in GET /slip-verify/order/{order_id}."""

    id: int
    order_id: int
    status: str
    risk_score: float | None = None
    ocr_amount: float | None = None
    ocr_reference: str | None = None
    created_at: datetime | None = None


class SlipUploadData(BaseModel):
    """``data`` of a slip upload; which fields are set depends on ``status``:
    verified / review: verification_id, order_id, amount, reference, risk_score
    (verified also bank, date, time, sender_name, receiver_name, verified_at;
    review also pending_reason: bank_check | risk_review | ocr_unavailable);
    amount_mismatch: expected_amount, detected_amount, risk_score;
    duplicate_image / duplicate_reference: existing_verification_id
    (duplicate_image also existing_order_id); other refusals: risk_score."""

    verification_id: int | None = None
    order_id: int | None = None
    amount: float | None = None
    reference: str | None = None
    bank: str | None = None
    date: str | None = None
    time: str | None = None
    sender_name: str | None = None
    receiver_name: str | None = None
    risk_score: float | None = None
    verified_at: str | None = None
    pending_reason: str | None = None
    expected_amount: float | None = None
    detected_amount: float | None = None
    existing_verification_id: int | None = None
    existing_order_id: int | None = None


class SlipUploadResult(BaseModel):
    """Answer of POST /slip-verify/upload (and the deprecated /checkslip). The
    HTTP status is 200 except order_not_found 404, ocr_failed 422,
    order_already_paid 400, unsupported_media_type 415."""

    success: bool
    status: str
    message: str
    data: SlipUploadData | None = None

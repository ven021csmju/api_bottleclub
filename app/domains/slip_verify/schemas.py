from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


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

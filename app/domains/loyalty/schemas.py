from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LoyaltyPointsEarn(BaseModel):
    customer_id: int
    points: int = Field(..., gt=0)
    reference_type: Optional[str] = Field(None, max_length=50)
    reference_id: Optional[int] = None
    notes: Optional[str] = None


class LoyaltyPointsRedeem(BaseModel):
    customer_id: int
    points: int = Field(..., gt=0)
    reference_type: Optional[str] = Field(None, max_length=50)
    reference_id: Optional[int] = None
    notes: Optional[str] = None


class LoyaltyTransactionResponse(BaseModel):
    id: int
    customer_id: int
    transaction_type: str
    points: int
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LoyaltyTransactionListResponse(BaseModel):
    transactions: list[LoyaltyTransactionResponse]
    total: int
    page: int
    per_page: int


class LoyaltyBalanceResponse(BaseModel):
    customer_id: int
    customer_name: str
    balance: int
    pending_expiring: int

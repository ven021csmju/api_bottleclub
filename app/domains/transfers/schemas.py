from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TransferItemCreate(BaseModel):
    product_id: int
    quantity_requested: int = Field(..., gt=0)
    lot_id: Optional[int] = None


class StockTransferCreate(BaseModel):
    dest_branch_id: int
    items: list[TransferItemCreate] = Field(..., min_length=1)
    notes: Optional[str] = None


class TransferItemResponse(BaseModel):
    id: int
    product_id: int
    quantity_requested: int
    quantity_shipped: int
    quantity_received: int
    quantity_damaged: int
    lot_id: Optional[int] = None

    model_config = {"from_attributes": True}


class StockTransferResponse(BaseModel):
    id: int
    transfer_number: str
    source_branch_id: int
    dest_branch_id: int
    status: str
    items: list[TransferItemResponse] = []
    requested_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class StockTransferListResponse(BaseModel):
    transfers: list[StockTransferResponse]
    total: int
    page: int
    per_page: int


class TransferStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class TransferShipItemCreate(BaseModel):
    transfer_item_id: int
    quantity_shipped: int = Field(..., gt=0)
    lot_id: Optional[int] = None


class TransferShipItems(BaseModel):
    items: list[TransferShipItemCreate] = Field(..., min_length=1)


class TransferReceiveItemCreate(BaseModel):
    transfer_item_id: int
    quantity_received: int = Field(..., ge=0)
    quantity_damaged: int = Field(0, ge=0)


class TransferReceiveItems(BaseModel):
    items: list[TransferReceiveItemCreate] = Field(..., min_length=1)

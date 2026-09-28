from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CustomerAddressCreate(BaseModel):
    customer_id: int
    recipient_name: str = Field(..., max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    address_line: str = Field(..., max_length=500)
    subdistrict: Optional[str] = Field(None, max_length=255)
    district: Optional[str] = Field(None, max_length=255)
    province: Optional[str] = Field(None, max_length=255)
    postal_code: Optional[str] = Field(None, max_length=20)
    is_default: bool = False


class CustomerAddressUpdate(BaseModel):
    recipient_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    address_line: Optional[str] = Field(None, max_length=500)
    subdistrict: Optional[str] = Field(None, max_length=255)
    district: Optional[str] = Field(None, max_length=255)
    province: Optional[str] = Field(None, max_length=255)
    postal_code: Optional[str] = Field(None, max_length=20)
    is_default: Optional[bool] = None


class CustomerAddressResponse(BaseModel):
    id: int
    customer_id: int
    recipient_name: str
    phone: Optional[str] = None
    address_line: str
    subdistrict: Optional[str] = None
    district: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomerAddressListResponse(BaseModel):
    addresses: list[CustomerAddressResponse]

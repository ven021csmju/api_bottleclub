from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    first_name: str = Field(..., max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    date_of_birth: Optional[date] = None


class CustomerUpdate(BaseModel):
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    date_of_birth: Optional[date] = None


class CustomerResponse(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    date_of_birth: Optional[date] = None
    loyalty_points_balance: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomerListResponse(BaseModel):
    customers: list[CustomerResponse]
    total: int
    page: int
    per_page: int

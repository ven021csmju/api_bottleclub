from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, EmailStr, field_validator


# ---------------------------------------------------------------------------
# User schemas
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    """Schema สำหรับรับข้อมูลเมื่อสร้าง User ใหม่"""
    name: str
    email: EmailStr


class UserUpdate(BaseModel):
    """Schema สำหรับรับข้อมูลเมื่ออัปเดต User"""
    name: str | None = None
    email: EmailStr | None = None


class UserResponse(BaseModel):
    """Schema สำหรับส่งข้อมูล User กลับไปยัง client"""
    id: int
    name: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Product schemas
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    """Schema สำหรับรับข้อมูลเมื่อสร้าง Product ใหม่"""
    name: str
    description: str | None = None
    price: Decimal
    stock: int = 0

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("price must be greater than 0")
        return v

    @field_validator("stock")
    @classmethod
    def stock_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("stock must be >= 0")
        return v


class ProductUpdate(BaseModel):
    """Schema สำหรับรับข้อมูลเมื่ออัปเดต Product"""
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    stock: int | None = None

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("price must be greater than 0")
        return v

    @field_validator("stock")
    @classmethod
    def stock_must_be_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("stock must be >= 0")
        return v


class ProductResponse(BaseModel):
    """Schema สำหรับส่งข้อมูล Product กลับไปยัง client"""
    id: int
    name: str
    description: str | None
    price: Decimal
    stock: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

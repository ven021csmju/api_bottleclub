from datetime import datetime
from pydantic import BaseModel, EmailStr


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

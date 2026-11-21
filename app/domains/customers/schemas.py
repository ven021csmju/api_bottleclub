from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domains.orders.service import OrderService


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


#: LINE's ``sub``: U and 32 hex digits.
LINE_SUB_PATTERN = r"^U[0-9a-f]{32}$"
#: A whole address: no wildcard (* % ?), no space, one @, a dot in the domain.
EMAIL_PATTERN = r"^[^\s@*%?]+@[^\s@*%?]+\.[^\s@*%?.]+$"
#: A whole number as typed: digits, spaces, dashes, brackets, a leading +.
PHONE_PATTERN = r"^\+?[0-9(][0-9 ()-]*$"


class CustomerLookupRequest(BaseModel):
    """POST /customers/lookup (service key ``customers.lookup``): exact
    identifiers, never a pattern; every one given must name the customer. In
    the body, so a phone or email stays out of URLs and access logs."""

    line_sub: Optional[str] = Field(None, pattern=LINE_SUB_PATTERN)
    email: Optional[str] = Field(None, max_length=255, pattern=EMAIL_PATTERN, repr=False)
    phone: Optional[str] = Field(None, max_length=50, pattern=PHONE_PATTERN, repr=False)

    model_config = {"extra": "forbid"}

    @field_validator("email")
    @classmethod
    def lower_email(cls, value: Optional[str]) -> Optional[str]:
        return value.lower() if value is not None else None

    @field_validator("phone")
    @classmethod
    def whole_phone(cls, value: Optional[str]) -> Optional[str]:
        """The digits as POST /orders/track compares them; a part of a number
        (fewer than 9 digits, or more than 10 once +66 is 0) is refused."""
        if value is None:
            return None
        digits = OrderService.normalize_contact(value)
        if digits is None or not 9 <= len(digits) <= 10 or not digits.startswith("0"):
            raise ValueError("phone must be a whole Thai number (0XXXXXXXX[X] or +66…)")
        return digits

    @model_validator(mode="after")
    def at_least_one(self) -> "CustomerLookupRequest":
        if self.line_sub is None and self.email is None and self.phone is None:
            raise ValueError("give line_sub, email or phone")
        return self

    def used(self) -> list[str]:
        """The identifiers given, by name (for the log: never their values)."""
        return [name for name in ("line_sub", "email", "phone") if getattr(self, name) is not None]


class CustomerLookupResponse(BaseModel):
    """What a service key gets of a customer: never the phone or email (the
    caller has them) or the date of birth."""

    id: int
    display_name: str
    loyalty_points_balance: int

    @classmethod
    def of(cls, customer) -> "CustomerLookupResponse":
        name = " ".join(p for p in (customer.first_name, customer.last_name) if p)
        return cls(id=customer.id, display_name=name, loyalty_points_balance=customer.loyalty_points_balance)

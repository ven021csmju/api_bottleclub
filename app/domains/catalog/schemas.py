from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

#: The screen an item goes to: none (no screen), kitchen or bar (Phase 38c).
Station = Literal["none", "kitchen", "bar"]


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------
class CategoryCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: int = 0
    station: Station = "none"


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    station: Optional[Station] = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: int
    is_active: bool
    station: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CategoryListResponse(BaseModel):
    categories: list[CategoryResponse]
    total: int


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------
class ProductCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    category_id: Optional[int] = None
    sku: str = Field(..., max_length=100)
    barcode: Optional[str] = Field(None, max_length=255)
    selling_price: Decimal = Field(..., gt=0, decimal_places=2)
    # The shop's cost of one unit (the inventory report values stock with it).
    # Written here, read only by catalog editors (GET /catalog/products/costs):
    # never in ProductResponse, which every cashier reads (Phase 47).
    cost_price: Decimal = Field(Decimal("0"), ge=0, decimal_places=2)
    unit: str = Field("each", max_length=20)
    track_inventory: bool = True
    has_expiry: bool = False
    image_url: Optional[str] = None
    # None: the category's station.
    station: Optional[Station] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    category_id: Optional[int] = None
    sku: Optional[str] = Field(None, max_length=100)
    barcode: Optional[str] = Field(None, max_length=255)
    selling_price: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    cost_price: Optional[Decimal] = Field(None, ge=0, decimal_places=2)
    unit: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None
    track_inventory: Optional[bool] = None
    has_expiry: Optional[bool] = None
    image_url: Optional[str] = None
    # null: back to the category's station.
    station: Optional[Station] = None

    @model_validator(mode="after")
    def cost_is_a_number(self) -> "ProductUpdate":
        if "cost_price" in self.model_fields_set and self.cost_price is None:
            raise ValueError("cost_price cannot be null (0 for no cost)")
        return self


class ProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    category_id: Optional[int] = None
    sku: str
    barcode: Optional[str] = None
    selling_price: Decimal
    unit: str
    is_active: bool
    track_inventory: bool
    has_expiry: bool
    image_url: Optional[str] = None
    # Its own station; None: the category's (what the product form edits).
    station: Optional[str] = None
    # The screen its order lines go to: station, else the category's, else "none" (Phase 42).
    effective_station: Station
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductCost(BaseModel):
    """GET /catalog/products/costs: catalog editors only (Phase 47)."""
    product_id: int
    sku: str
    cost_price: Decimal


class ProductListResponse(BaseModel):
    products: list[ProductResponse]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------
class SupplierCreate(BaseModel):
    name: str = Field(..., max_length=255)
    contact_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    contact_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierResponse(BaseModel):
    id: int
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SupplierListResponse(BaseModel):
    suppliers: list[SupplierResponse]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# SupplierProduct
# ---------------------------------------------------------------------------
class SupplierProductCreate(BaseModel):
    product_id: int
    cost_price: Decimal = Field(..., ge=0, decimal_places=2)
    supplier_sku: Optional[str] = Field(None, max_length=100)


class SupplierProductUpdate(BaseModel):
    cost_price: Optional[Decimal] = Field(None, ge=0, decimal_places=2)
    supplier_sku: Optional[str] = Field(None, max_length=100)


class SupplierProductResponse(BaseModel):
    id: int
    supplier_id: int
    product_id: int
    cost_price: Decimal
    supplier_sku: Optional[str] = None
    product_name: str
    product_sku: str

    model_config = {"from_attributes": True}

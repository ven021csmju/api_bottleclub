"""Public storefront catalog (Phase 50): what a shopper may see of a product."""
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel

WineType = Literal["red", "white", "sparkling", "rose", "dessert"]


class StorefrontWine(BaseModel):
    """From wine_products (code = the product's sku); null when there is none."""
    type: Optional[WineType] = None
    country: Optional[str] = None
    region: Optional[str] = None
    alcohol: Optional[str] = None
    volume: Optional[str] = None


class StorefrontProduct(BaseModel):
    id: int
    sku: str
    name: str
    description: Optional[str] = None
    price: Decimal
    unit: str
    # Relative (/demo-wines/…: the storefront's own /public) or absolute.
    image_url: Optional[str] = None
    # A demo product: the storefront shows a "สินค้าตัวอย่าง" badge; it cannot be bought.
    is_demo: bool
    wine: Optional[StorefrontWine] = None


class StorefrontProductList(BaseModel):
    items: list[StorefrontProduct]
    total: int
    page: int
    per_page: int
    pages: int

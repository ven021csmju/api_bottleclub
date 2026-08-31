from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WineProductResponse(BaseModel):
    id: int
    code: str
    product_name: Optional[str] = None
    brands: Optional[str] = None
    categories_en: Optional[str] = None
    origins_en: Optional[str] = None
    countries_en: Optional[str] = None
    quantity: Optional[str] = None
    ingredients_text: Optional[str] = None
    image_url: Optional[str] = None
    image_small_url: Optional[str] = None
    alcohol_100g: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WineProductListResponse(BaseModel):
    items: list[WineProductResponse]
    total: int
    page: int
    per_page: int
    pages: int

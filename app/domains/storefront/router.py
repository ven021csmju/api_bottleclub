"""GET /storefront/products: the public storefront catalog (Phase 50, no login).

Behind STOREFRONT_CATALOG_ENABLED (off in production until the legal review,
owner Q7): off, every route here answers 404 as if it did not exist.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.domains.storefront.schemas import StorefrontProduct, StorefrontProductList, WineType
from app.domains.storefront.service import StorefrontService
from app.middleware.rate_limit import limiter
from app.shared.exceptions import NotFoundException

router = APIRouter()
CACHE = "public, max-age=60"


def catalog_enabled() -> None:
    if not settings.storefront_catalog_enabled:
        raise NotFoundException(detail="Not Found")


@router.get("/products", response_model=StorefrontProductList, dependencies=[Depends(catalog_enabled)],
            responses={404: {"description": "The storefront catalog is off (STOREFRONT_CATALOG_ENABLED)"}})
@limiter.limit(settings.RATE_LIMIT_STOREFRONT_CATALOG)
def list_storefront_products(
    request: Request,
    response: Response,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    type: Optional[WineType] = Query(None, description="The wine type (from wine_products)"),
    country: Optional[str] = Query(None, max_length=100),
    search: Optional[str] = Query(None, max_length=100, description="In the name and description"),
    sort: Literal["name", "price", "-price"] = Query("name"),
    db: Session = Depends(get_db),
) -> StorefrontProductList:
    """Demo products (``is_demo``: show a "สินค้าตัวอย่าง" badge) and the products
    the shop put online; live, active, priced. Search terms are not logged."""
    items, total = StorefrontService.list(
        db, page=page, per_page=per_page, type=type, country=country, search=search, sort=sort
    )
    response.headers["Cache-Control"] = CACHE
    return StorefrontProductList(
        items=items, total=total, page=page, per_page=per_page,
        pages=(total + per_page - 1) // per_page if total else 0,
    )


@router.get("/products/{product_id}", response_model=StorefrontProduct, dependencies=[Depends(catalog_enabled)],
            responses={404: {"description": "Not on the storefront, or the catalog is off"}})
@limiter.limit(settings.RATE_LIMIT_STOREFRONT_CATALOG)
def get_storefront_product(
    request: Request, response: Response, product_id: int, db: Session = Depends(get_db)
) -> StorefrontProduct:
    product = StorefrontService.get(db, product_id)
    response.headers["Cache-Control"] = CACHE
    return product

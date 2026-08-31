from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.wine_products.schemas import WineProductListResponse, WineProductResponse
from app.domains.wine_products.service import WineProductService
from app.middleware.auth import require_permission
from app.shared.pagination import paginate
from app.db.models import User

router = APIRouter()


@router.get("/", response_model=WineProductListResponse)
def list_wine_products(
    search: Optional[str] = Query(None),
    brands: Optional[str] = Query(None),
    countries: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.read")),
) -> WineProductListResponse:
    items, total = WineProductService.list(
        db,
        search=search,
        brands=brands,
        countries=countries,
        category=category,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total else 0
    return WineProductListResponse(
        items=items, total=total, page=page, per_page=per_page, pages=pages
    )


@router.get("/{wine_product_id}", response_model=WineProductResponse)
def get_wine_product(
    wine_product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.read")),
) -> WineProductResponse:
    return WineProductService.get(db, wine_product_id)

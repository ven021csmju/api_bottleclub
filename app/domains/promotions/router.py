from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.database import get_db
from app.domains.promotions.schemas import (
    PromotionCreate,
    PromotionListResponse,
    PromotionResponse,
    PromotionUpdate,
)
from app.domains.promotions.service import PromotionService
from app.middleware.auth import require_permission
from database.models import User
from app.shared.pagination import PaginationParams

router = APIRouter()


@router.get("/", response_model=PromotionListResponse)
def list_promotions(
    is_active: Optional[bool] = Query(None),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("promotions.read")),
) -> PromotionListResponse:
    promotions, total = PromotionService.list(
        db, user.organization_id, is_active=is_active,
        page=pagination.page, per_page=pagination.per_page,
    )
    return PromotionListResponse(
        promotions=promotions,
        total=total,
        page=pagination.page,
        per_page=pagination.per_page,
    )


@router.get("/{promotion_id}", response_model=PromotionResponse)
def get_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("promotions.read")),
) -> PromotionResponse:
    return PromotionService.get(db, user.organization_id, promotion_id)


@router.post("/", response_model=PromotionResponse, status_code=201)
def create_promotion(
    data: PromotionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("promotions.create")),
) -> PromotionResponse:
    return PromotionService.create(
        db, user.organization_id, **data.model_dump()
    )


@router.put("/{promotion_id}", response_model=PromotionResponse)
def update_promotion(
    promotion_id: int,
    data: PromotionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("promotions.update")),
) -> PromotionResponse:
    return PromotionService.update(
        db, user.organization_id, promotion_id,
        **data.model_dump(exclude_unset=True),
    )


@router.delete("/{promotion_id}", status_code=204)
def delete_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("promotions.delete")),
) -> None:
    PromotionService.delete(db, user.organization_id, promotion_id)

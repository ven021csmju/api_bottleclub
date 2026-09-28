from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.promotions.schemas import (
    PromotionBulkItem,
    PromotionBulkResponse,
    PromotionCreate,
    PromotionListResponse,
    PromotionMutationResponse,
    PromotionResponse,
    PromotionUpdate,
)
from app.domains.promotions.service import PromotionService
from app.middleware.auth import require_permission
from app.db.models import User

router = APIRouter()


def _response(promotion) -> PromotionResponse:
    return PromotionResponse.model_validate(promotion)


@router.get("/promotions", response_model=PromotionListResponse)
def list_promotions(
    featured: bool | None = Query(None),
    db: Session = Depends(get_db),
) -> PromotionListResponse:
    return PromotionListResponse(
        promotions=[_response(item) for item in PromotionService.list(db, featured)]
    )


@router.post("/admin/promotions", response_model=PromotionMutationResponse, status_code=status.HTTP_201_CREATED)
def create_promotion(
    data: PromotionCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("promotions.create")),
) -> PromotionMutationResponse:
    return PromotionMutationResponse(
        promotion=_response(PromotionService.create(db, data.model_dump(by_alias=False)))
    )


@router.put("/admin/promotions", response_model=PromotionMutationResponse)
def update_promotion(
    data: PromotionUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("promotions.update")),
) -> PromotionMutationResponse:
    return PromotionMutationResponse(
        promotion=_response(
            PromotionService.update(db, data.model_dump(exclude_unset=True, by_alias=False))
        )
    )


@router.put("/admin/promotions/bulk", response_model=PromotionBulkResponse)
def bulk_update_promotions(
    data: list[PromotionBulkItem],
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("promotions.update")),
) -> PromotionBulkResponse:
    count = PromotionService.bulk_update(
        db, [item.model_dump(exclude_unset=True, by_alias=False) for item in data]
    )
    return PromotionBulkResponse(count=count)


@router.delete("/admin/promotions")
def delete_promotion(
    promotion_id: str = Query(..., alias="id"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("promotions.delete")),
) -> dict:
    PromotionService.delete(db, promotion_id)
    return {"success": True, "message": "ลบโปรโมชั่นสำเร็จ"}

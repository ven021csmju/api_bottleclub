from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Product, Review, User
from app.domains.reviews.schemas import (
    ReviewCreate,
    ReviewDetailResponse,
    ReviewListResponse,
    ReviewModerationUpdate,
    ReviewResponse,
)
from app.domains.reviews.service import ReviewService
from app.middleware.auth import require_permission

router = APIRouter()


@router.get("/", response_model=ReviewListResponse)
def list_reviews(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reviews.read")),
    product_id: int | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> ReviewListResponse:
    items, total = ReviewService.list(
        db,
        user.organization_id,
        product_id=product_id,
        status=status,
        page=page,
        per_page=per_page,
    )
    reviews = _build_details(db, items)
    return ReviewListResponse(
        reviews=reviews, total=total, page=page, per_page=per_page
    )


@router.get("/{review_id}", response_model=ReviewDetailResponse)
def get_review(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reviews.read")),
) -> ReviewDetailResponse:
    review = ReviewService.get(db, user.organization_id, review_id)
    return _build_details(db, [review])[0]


@router.post("/", response_model=ReviewResponse, status_code=201)
def create_review(
    request: Request,
    body: ReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reviews.create")),
) -> ReviewResponse:
    review = ReviewService.create(
        db,
        user.organization_id,
        body.model_dump(),
        user_id=user.id,
        request_id=getattr(request.state, "request_id", ""),
    )
    return ReviewResponse.model_validate(review)


@router.patch("/{review_id}/moderation", response_model=ReviewResponse)
def moderate_review(
    review_id: int,
    body: ReviewModerationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reviews.moderate")),
) -> ReviewResponse:
    review = ReviewService.moderate(
        db, user.organization_id, review_id, body.status
    )
    return ReviewResponse.model_validate(review)


def _build_details(db: Session, reviews: list[Review]) -> list[ReviewDetailResponse]:
    details = []
    for r in reviews:
        product = db.get(Product, r.product_id)
        detail = ReviewDetailResponse.model_validate(r)
        detail.product_name = product.name if product else None
        detail.product_sku = product.sku if product else None
        details.append(detail)
    return details

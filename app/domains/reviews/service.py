from sqlalchemy.orm import Session

from app.db.models import Product, Review
from app.db.repositories.customers import CustomerRepository
from app.db.repositories.reviews import ReviewRepository
from app.services import user_events
from app.shared.exceptions import BadRequestException, NotFoundException

MODERATION_STATUSES = {"pending", "approved", "rejected", "hidden"}


class ReviewService:
    @staticmethod
    def _get_product(db: Session, organization_id: int, product_id: int) -> Product:
        product = ReviewRepository.get_product(db, product_id)
        if product is None or product.organization_id != organization_id:
            raise NotFoundException(detail="Product not found")
        return product

    @staticmethod
    def _get_customer(db: Session, organization_id: int, customer_id: int):
        customer = CustomerRepository.get_org_customer(
            db, organization_id, customer_id
        )
        if customer is None:
            raise NotFoundException(detail="Customer not found")
        return customer

    @staticmethod
    def list(
        db: Session,
        organization_id: int,
        product_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Review], int]:
        return ReviewRepository.list_org_reviews(
            db,
            organization_id,
            product_id=product_id,
            status=status,
            page=page,
            per_page=per_page,
        )

    @staticmethod
    def get(db: Session, organization_id: int, review_id: int) -> Review:
        review = ReviewRepository.get_org_review(db, organization_id, review_id)
        if review is None:
            raise NotFoundException(detail="Review not found")
        return review

    @staticmethod
    def create(
        db: Session,
        organization_id: int,
        data: dict,
        user_id: int | None = None,
        request_id: str = "",
    ) -> Review:
        ReviewService._get_product(db, organization_id, data["product_id"])
        ReviewService._get_customer(db, organization_id, data["customer_id"])

        review = Review(
            product_id=data["product_id"],
            customer_id=data["customer_id"],
            order_id=data.get("order_id"),
            rating=data["rating"],
            comment=data.get("comment"),
            status="pending",
        )
        ReviewRepository.add(db, review)
        db.commit()
        db.refresh(review)
        # Emitted after the transaction committed; never raises.
        user_events.publish_user_event_sync(
            "review_created",
            user_id,
            request_id,
            {"review_id": review.id, "product_id": review.product_id},
        )
        return review

    @staticmethod
    def moderate(
        db: Session, organization_id: int, review_id: int, status: str
    ) -> Review:
        if status not in MODERATION_STATUSES:
            raise BadRequestException(detail=f"Invalid review status: '{status}'")

        review = ReviewService.get(db, organization_id, review_id)
        review.status = status
        db.commit()
        db.refresh(review)
        return review

from sqlalchemy.orm import Session

from app.db.models import WineProduct
from app.db.repositories.wine_products.wine_product_repository import WineProductRepository
from app.shared.exceptions import NotFoundException


class WineProductService:
    @staticmethod
    def list(
        db: Session,
        search: str | None = None,
        brands: str | None = None,
        countries: str | None = None,
        category: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[WineProduct], int]:
        return WineProductRepository.list_query(
            db,
            search=search,
            brands=brands,
            countries=countries,
            category=category,
            page=page,
            per_page=per_page,
        )

    @staticmethod
    def get(db: Session, wine_product_id: int) -> WineProduct:
        item = WineProductRepository.get(db, wine_product_id)
        if item is None:
            raise NotFoundException(detail="Wine product not found")
        return item

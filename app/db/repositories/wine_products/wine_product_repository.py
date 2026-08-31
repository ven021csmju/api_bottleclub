from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import WineProduct


class WineProductRepository:
    @staticmethod
    def list_query(
        db: Session,
        search: str | None = None,
        brands: str | None = None,
        countries: str | None = None,
        category: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[WineProduct], int]:
        stmt = select(WineProduct)

        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(
                    WineProduct.product_name.ilike(like),
                    WineProduct.brands.ilike(like),
                    WineProduct.code.ilike(like),
                )
            )

        if brands:
            stmt = stmt.where(WineProduct.brands.ilike(f"%{brands}%"))

        if countries:
            stmt = stmt.where(WineProduct.countries_en.ilike(f"%{countries}%"))

        if category:
            stmt = stmt.where(WineProduct.categories_en.ilike(f"%{category}%"))

        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

        stmt = (
            stmt.order_by(WineProduct.product_name, WineProduct.code)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        items = list(db.scalars(stmt).all())
        return items, total

    @staticmethod
    def get(db: Session, wine_product_id: int) -> WineProduct | None:
        return db.get(WineProduct, wine_product_id)

    @staticmethod
    def find_by_code(db: Session, code: str) -> WineProduct | None:
        return db.scalar(select(WineProduct).where(WineProduct.code == code))

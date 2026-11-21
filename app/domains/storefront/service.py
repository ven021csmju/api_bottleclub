"""Public storefront catalog (Phase 50, 50A-2).

Only ``product_scope.STOREFRONT`` products of the storefront's organization:
demo products and the real ones a catalog editor put online, live, active and
priced. Never a cost, a stock figure, a barcode or a station.
"""
from __future__ import annotations

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import Organization, Product, WineProduct
from app.db.product_scope import STOREFRONT
from app.domains.storefront.schemas import StorefrontProduct, StorefrontWine
from app.shared.exceptions import NotFoundException

# wine_products.categories_en -> the storefront's type.
WINE_TYPES = {
    "red wines": "red", "white wines": "white", "sparkling wines": "sparkling",
    "rosé wines": "rose", "rose wines": "rose", "dessert wines": "dessert",
}
TYPE_LABELS = {v: k for k, v in WINE_TYPES.items() if k != "rose wines"}
SORTS = {
    "name": (Product.name.asc(), Product.id.asc()),
    "price": (Product.selling_price.asc(), Product.id.asc()),
    "-price": (Product.selling_price.desc(), Product.id.asc()),
}


def _organization_id(db: Session) -> int | None:
    query = select(Organization.id).where(Organization.is_active.is_(True))
    if settings.STOREFRONT_ORGANIZATION_ID is not None:
        return db.scalar(query.where(Organization.id == settings.STOREFRONT_ORGANIZATION_ID))
    ids = db.scalars(query.order_by(Organization.id).limit(2)).all()
    return ids[0] if len(ids) == 1 else None


def _query(org_id: int) -> Select:
    return (
        select(Product, WineProduct)
        .outerjoin(WineProduct, WineProduct.code == Product.sku)
        .where(Product.organization_id == org_id, STOREFRONT)
    )


def _answer(product: Product, wine: WineProduct | None) -> StorefrontProduct:
    return StorefrontProduct(
        id=product.id, sku=product.sku, name=product.name, description=product.description,
        price=product.selling_price, unit=product.unit, image_url=product.image_url,
        is_demo=product.is_demo,
        wine=None if wine is None else StorefrontWine(
            type=WINE_TYPES.get((wine.categories_en or "").strip().lower()),
            country=wine.countries_en, region=wine.origins_en,
            alcohol=wine.alcohol_100g, volume=wine.quantity,
        ),
    )


class StorefrontService:
    @staticmethod
    def list(
        db: Session, *, page: int, per_page: int, type: str | None = None,
        country: str | None = None, search: str | None = None, sort: str = "name",
    ) -> tuple[list[StorefrontProduct], int]:
        org_id = _organization_id(db)
        if org_id is None:
            return [], 0
        stmt = _query(org_id)
        if type is not None:
            labels = [k for k, v in WINE_TYPES.items() if v == type]
            stmt = stmt.where(func.lower(func.trim(WineProduct.categories_en)).in_(labels))
        if country:
            stmt = stmt.where(func.lower(WineProduct.countries_en) == country.strip().lower())
        if search:
            like = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(or_(Product.name.ilike(like, escape="\\"),
                                  Product.description.ilike(like, escape="\\")))
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.execute(
            stmt.order_by(*SORTS[sort]).offset((page - 1) * per_page).limit(per_page)
        ).all()
        return [_answer(p, w) for p, w in rows], total

    @staticmethod
    def get(db: Session, product_id: int) -> StorefrontProduct:
        org_id = _organization_id(db)
        row = None if org_id is None else db.execute(
            _query(org_id).where(Product.id == product_id)
        ).first()
        if row is None:
            raise NotFoundException(detail="Product not found")
        return _answer(*row)

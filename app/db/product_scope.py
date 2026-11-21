"""Which products a reader may see (Phase 50).

A demo product (``products.is_demo``, sku ``DEMO-``, made by
scripts/seed_demo_wines.py only) is for the public storefront catalog. No staff
route, order, purchase, transfer, stock movement or report may see or use it:
every staff query of ``products`` adds ``STAFF`` (or ``staff_only`` for a
product loaded by id). tests/integration/test_demo_products_hidden.py walks
them all.
"""
from __future__ import annotations

from sqlalchemy import and_, or_

from app.db.models import Product

DEMO_PREFIX = "DEMO-"

# Staff side: never a demo product.
STAFF = Product.is_demo.is_(False)

# The public storefront: demo products and the real ones the shop put online,
# live, active and priced.
STOREFRONT = and_(
    or_(Product.is_demo.is_(True), Product.is_online.is_(True)),
    Product.is_active.is_(True),
    Product.deleted_at.is_(None),
    Product.selling_price > 0,
)


def staff_only(product: Product | None) -> Product | None:
    """``product``, or None when it is a demo product (a staff caller gets 404)."""
    return None if product is None or product.is_demo else product


def is_demo_sku(sku: str | None) -> bool:
    return bool(sku) and sku.startswith(DEMO_PREFIX)


def refuse_demo_sku(sku: str | None) -> None:
    """Staff may not make or rename a product into the DEMO- range (026's CHECK
    would turn it into a demo product)."""
    from app.shared.exceptions import UnprocessableException

    if is_demo_sku(sku):
        raise UnprocessableException(
            detail=f"SKUs starting with {DEMO_PREFIX} are reserved for demo products",
            code="DEMO_SKU_RESERVED",
        )


def refuse_demo_products(products) -> None:
    """A demo product is never sold, bought, moved or stocked by the shop."""
    from app.shared.exceptions import UnprocessableException

    demo = sorted(p.id for p in products if p is not None and p.is_demo)
    if demo:
        raise UnprocessableException(
            detail=f"Demo products are not for sale: {', '.join(map(str, demo))}",
            code="DEMO_PRODUCT_NOT_FOR_SALE",
        )

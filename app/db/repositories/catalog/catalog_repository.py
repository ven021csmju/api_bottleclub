from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Category, Product, Supplier, SupplierProduct


class CatalogRepository:
    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------
    @staticmethod
    def list_categories(db: Session, org_id: int) -> list[Category]:
        stmt = (
            select(Category)
            .where(Category.organization_id == org_id)
            .order_by(Category.sort_order, Category.name)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_category(db: Session, category_id: int) -> Category | None:
        return db.get(Category, category_id)

    @staticmethod
    def find_category_by_name(db: Session, org_id: int, name: str) -> Category | None:
        return db.scalar(
            select(Category).where(
                Category.organization_id == org_id,
                Category.name == name,
            )
        )

    @staticmethod
    def find_category_name_conflict(
        db: Session, org_id: int, exclude_category_id: int, name: str
    ) -> Category | None:
        return db.scalar(
            select(Category).where(
                Category.organization_id == org_id,
                Category.name == name,
                Category.id != exclude_category_id,
            )
        )

    @staticmethod
    def count_child_categories(db: Session, org_id: int, category_id: int) -> int:
        return (
            db.scalar(
                select(func.count()).where(
                    Category.organization_id == org_id,
                    Category.parent_id == category_id,
                )
            )
            or 0
        )

    @staticmethod
    def count_category_products(db: Session, org_id: int, category_id: int) -> int:
        return (
            db.scalar(
                select(func.count()).where(
                    Product.organization_id == org_id,
                    Product.category_id == category_id,
                    Product.deleted_at.is_(None),
                )
            )
            or 0
        )

    @staticmethod
    def add_category(db: Session, category: Category) -> Category:
        db.add(category)
        db.flush()
        return category

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    @staticmethod
    def list_products(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        category_id: int | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[Product], int]:
        stmt = select(Product).where(
            Product.organization_id == org_id,
            Product.deleted_at.is_(None),
        )

        if search:
            like_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Product.name.ilike(like_pattern),
                    Product.sku.ilike(like_pattern),
                    Product.barcode.ilike(like_pattern),
                )
            )

        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)

        if is_active is not None:
            stmt = stmt.where(Product.is_active == is_active)

        total = db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        stmt = stmt.order_by(Product.name).offset((page - 1) * per_page).limit(per_page)
        products = list(db.scalars(stmt).all())
        return products, total

    @staticmethod
    def get_product(db: Session, product_id: int) -> Product | None:
        return db.get(Product, product_id)

    @staticmethod
    def find_by_sku(db: Session, org_id: int, sku: str) -> Product | None:
        return db.scalar(
            select(Product).where(
                Product.organization_id == org_id,
                Product.sku == sku,
                Product.deleted_at.is_(None),
            )
        )

    @staticmethod
    def find_by_barcode(db: Session, org_id: int, barcode: str) -> Product | None:
        return db.scalar(
            select(Product).where(
                Product.organization_id == org_id,
                Product.barcode == barcode,
                Product.deleted_at.is_(None),
            )
        )

    @staticmethod
    def find_sku_conflict(
        db: Session, org_id: int, exclude_product_id: int, sku: str
    ) -> Product | None:
        return db.scalar(
            select(Product).where(
                Product.organization_id == org_id,
                Product.sku == sku,
                Product.id != exclude_product_id,
                Product.deleted_at.is_(None),
            )
        )

    @staticmethod
    def find_barcode_conflict(
        db: Session, org_id: int, exclude_product_id: int, barcode: str
    ) -> Product | None:
        return db.scalar(
            select(Product).where(
                Product.organization_id == org_id,
                Product.barcode == barcode,
                Product.id != exclude_product_id,
                Product.deleted_at.is_(None),
            )
        )

    @staticmethod
    def add_product(db: Session, product: Product) -> Product:
        db.add(product)
        db.flush()
        return product

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    @staticmethod
    def list_suppliers(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
    ) -> tuple[list[Supplier], int]:
        stmt = select(Supplier).where(Supplier.organization_id == org_id)

        if search:
            like_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Supplier.name.ilike(like_pattern),
                    Supplier.contact_name.ilike(like_pattern),
                )
            )

        total = db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        stmt = stmt.order_by(Supplier.name).offset((page - 1) * per_page).limit(per_page)
        suppliers = list(db.scalars(stmt).all())
        return suppliers, total

    @staticmethod
    def get_supplier(db: Session, supplier_id: int) -> Supplier | None:
        return db.get(Supplier, supplier_id)

    @staticmethod
    def find_supplier_by_name(db: Session, org_id: int, name: str) -> Supplier | None:
        return db.scalar(
            select(Supplier).where(
                Supplier.organization_id == org_id,
                Supplier.name == name,
            )
        )

    @staticmethod
    def find_supplier_name_conflict(
        db: Session, org_id: int, exclude_supplier_id: int, name: str
    ) -> Supplier | None:
        return db.scalar(
            select(Supplier).where(
                Supplier.organization_id == org_id,
                Supplier.name == name,
                Supplier.id != exclude_supplier_id,
            )
        )

    @staticmethod
    def add_supplier(db: Session, supplier: Supplier) -> Supplier:
        db.add(supplier)
        db.flush()
        return supplier

    # ------------------------------------------------------------------
    # Supplier Products
    # ------------------------------------------------------------------
    @staticmethod
    def list_supplier_products(db: Session, supplier_id: int) -> list[tuple]:
        stmt = (
            select(
                SupplierProduct,
                Product.name.label("product_name"),
                Product.sku.label("product_sku"),
            )
            .join(Product, SupplierProduct.product_id == Product.id)
            .where(SupplierProduct.supplier_id == supplier_id)
            .order_by(Product.name)
        )
        return db.execute(stmt).all()

    @staticmethod
    def get_supplier_product(db: Session, supplier_product_id: int) -> SupplierProduct | None:
        return db.get(SupplierProduct, supplier_product_id)

    @staticmethod
    def find_supplier_product_link(
        db: Session, supplier_id: int, product_id: int
    ) -> SupplierProduct | None:
        return db.scalar(
            select(SupplierProduct).where(
                SupplierProduct.supplier_id == supplier_id,
                SupplierProduct.product_id == product_id,
            )
        )

    @staticmethod
    def add_supplier_product(db: Session, sp: SupplierProduct) -> SupplierProduct:
        db.add(sp)
        db.flush()
        return sp

    @staticmethod
    def delete_supplier_product(db: Session, sp: SupplierProduct) -> None:
        db.delete(sp)
        db.flush()
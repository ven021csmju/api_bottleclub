import datetime
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domains.catalog.schemas import (
    CategoryCreate,
    CategoryListResponse,
    CategoryResponse,
    CategoryUpdate,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    SupplierCreate,
    SupplierListResponse,
    SupplierProductCreate,
    SupplierProductResponse,
    SupplierProductUpdate,
    SupplierResponse,
    SupplierUpdate,
)
from app.models import (
    Category,
    Product,
    Supplier,
    SupplierProduct,
)
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)


class CatalogService:
    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------
    @staticmethod
    def list_categories(db: Session, org_id: int) -> CategoryListResponse:
        stmt = (
            select(Category)
            .where(Category.organization_id == org_id)
            .order_by(Category.sort_order, Category.name)
        )
        categories = db.scalars(stmt).all()
        return CategoryListResponse(
            categories=[CategoryResponse.model_validate(c) for c in categories],
            total=len(categories),
        )

    @staticmethod
    def create_category(db: Session, org_id: int, data: CategoryCreate) -> Category:
        existing = db.scalar(
            select(Category).where(
                Category.organization_id == org_id,
                Category.name == data.name,
            )
        )
        if existing:
            raise ConflictException(
                detail=f"Category '{data.name}' already exists"
            )

        if data.parent_id is not None:
            parent = db.get(Category, data.parent_id)
            if not parent or parent.organization_id != org_id:
                raise NotFoundException(detail="Parent category not found")

        category = Category(
            organization_id=org_id,
            name=data.name,
            description=data.description,
            parent_id=data.parent_id,
            sort_order=data.sort_order,
        )
        db.add(category)
        db.flush()
        db.refresh(category)
        return category

    @staticmethod
    def update_category(
        db: Session, org_id: int, category_id: int, data: CategoryUpdate
    ) -> Category:
        category = db.get(Category, category_id)
        if not category or category.organization_id != org_id:
            raise NotFoundException(detail="Category not found")

        update_data = data.model_dump(exclude_unset=True)

        if "name" in update_data and update_data["name"] != category.name:
            conflict = db.scalar(
                select(Category).where(
                    Category.organization_id == org_id,
                    Category.name == update_data["name"],
                    Category.id != category_id,
                )
            )
            if conflict:
                raise ConflictException(
                    detail=f"Category '{update_data['name']}' already exists"
                )

        if "parent_id" in update_data and update_data["parent_id"] is not None:
            if update_data["parent_id"] == category_id:
                raise BadRequestException(
                    detail="Category cannot be its own parent"
                )
            parent = db.get(Category, update_data["parent_id"])
            if not parent or parent.organization_id != org_id:
                raise NotFoundException(detail="Parent category not found")

        for field, value in update_data.items():
            setattr(category, field, value)

        db.flush()
        db.refresh(category)
        return category

    @staticmethod
    def delete_category(db: Session, org_id: int, category_id: int) -> None:
        category = db.get(Category, category_id)
        if not category or category.organization_id != org_id:
            raise NotFoundException(detail="Category not found")

        child_count = db.scalar(
            select(func.count()).where(
                Category.organization_id == org_id,
                Category.parent_id == category_id,
            )
        )
        if child_count and child_count > 0:
            raise BadRequestException(
                detail="Cannot delete category with subcategories"
            )

        product_count = db.scalar(
            select(func.count()).where(
                Product.organization_id == org_id,
                Product.category_id == category_id,
                Product.deleted_at.is_(None),
            )
        )
        if product_count and product_count > 0:
            raise BadRequestException(
                detail="Cannot delete category with associated products"
            )

        category.is_active = False
        db.flush()

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    @staticmethod
    def list_products(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        search: Optional[str] = None,
        category_id: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> ProductListResponse:
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

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(total_stmt) or 0

        stmt = stmt.order_by(Product.name).offset((page - 1) * per_page).limit(per_page)
        products = db.scalars(stmt).all()

        return ProductListResponse(
            products=[ProductResponse.model_validate(p) for p in products],
            total=total,
            page=page,
            per_page=per_page,
        )

    @staticmethod
    def get_product(db: Session, org_id: int, product_id: int) -> Product:
        product = db.get(Product, product_id)
        if not product or product.organization_id != org_id or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")
        return product

    @staticmethod
    def create_product(db: Session, org_id: int, data: ProductCreate) -> Product:
        existing = db.scalar(
            select(Product).where(
                Product.organization_id == org_id,
                Product.sku == data.sku,
                Product.deleted_at.is_(None),
            )
        )
        if existing:
            raise ConflictException(
                detail=f"Product with SKU '{data.sku}' already exists"
            )

        if data.barcode:
            barcode_conflict = db.scalar(
                select(Product).where(
                    Product.organization_id == org_id,
                    Product.barcode == data.barcode,
                    Product.deleted_at.is_(None),
                )
            )
            if barcode_conflict:
                raise ConflictException(
                    detail=f"Product with barcode '{data.barcode}' already exists"
                )

        if data.category_id is not None:
            category = db.get(Category, data.category_id)
            if not category or category.organization_id != org_id:
                raise NotFoundException(detail="Category not found")

        product = Product(
            organization_id=org_id,
            name=data.name,
            description=data.description,
            category_id=data.category_id,
            sku=data.sku,
            barcode=data.barcode,
            selling_price=data.selling_price,
            unit=data.unit,
            track_inventory=data.track_inventory,
            has_expiry=data.has_expiry,
        )
        db.add(product)
        db.flush()
        db.refresh(product)
        return product

    @staticmethod
    def update_product(
        db: Session, org_id: int, product_id: int, data: ProductUpdate
    ) -> Product:
        product = db.get(Product, product_id)
        if not product or product.organization_id != org_id or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")

        update_data = data.model_dump(exclude_unset=True)

        if "sku" in update_data and update_data["sku"] != product.sku:
            sku_conflict = db.scalar(
                select(Product).where(
                    Product.organization_id == org_id,
                    Product.sku == update_data["sku"],
                    Product.id != product_id,
                    Product.deleted_at.is_(None),
                )
            )
            if sku_conflict:
                raise ConflictException(
                    detail=f"Product with SKU '{update_data['sku']}' already exists"
                )

        if "barcode" in update_data and update_data["barcode"] and update_data["barcode"] != product.barcode:
            barcode_conflict = db.scalar(
                select(Product).where(
                    Product.organization_id == org_id,
                    Product.barcode == update_data["barcode"],
                    Product.id != product_id,
                    Product.deleted_at.is_(None),
                )
            )
            if barcode_conflict:
                raise ConflictException(
                    detail=f"Product with barcode '{update_data['barcode']}' already exists"
                )

        if "category_id" in update_data and update_data["category_id"] is not None:
            category = db.get(Category, update_data["category_id"])
            if not category or category.organization_id != org_id:
                raise NotFoundException(detail="Category not found")

        for field, value in update_data.items():
            setattr(product, field, value)

        db.flush()
        db.refresh(product)
        return product

    @staticmethod
    def delete_product(db: Session, org_id: int, product_id: int) -> None:
        product = db.get(Product, product_id)
        if not product or product.organization_id != org_id or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")

        product.deleted_at = datetime.datetime.now(datetime.timezone.utc)
        db.flush()

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    @staticmethod
    def list_suppliers(
        db: Session,
        org_id: int,
        page: int = 1,
        per_page: int = 20,
        search: Optional[str] = None,
    ) -> SupplierListResponse:
        stmt = select(Supplier).where(Supplier.organization_id == org_id)

        if search:
            like_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Supplier.name.ilike(like_pattern),
                    Supplier.contact_name.ilike(like_pattern),
                )
            )

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(total_stmt) or 0

        stmt = stmt.order_by(Supplier.name).offset((page - 1) * per_page).limit(per_page)
        suppliers = db.scalars(stmt).all()

        return SupplierListResponse(
            suppliers=[SupplierResponse.model_validate(s) for s in suppliers],
            total=total,
            page=page,
            per_page=per_page,
        )

    @staticmethod
    def get_supplier(db: Session, org_id: int, supplier_id: int) -> Supplier:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")
        return supplier

    @staticmethod
    def create_supplier(db: Session, org_id: int, data: SupplierCreate) -> Supplier:
        existing = db.scalar(
            select(Supplier).where(
                Supplier.organization_id == org_id,
                Supplier.name == data.name,
            )
        )
        if existing:
            raise ConflictException(
                detail=f"Supplier '{data.name}' already exists"
            )

        supplier = Supplier(
            organization_id=org_id,
            name=data.name,
            contact_name=data.contact_name,
            phone=data.phone,
            email=data.email,
            address=data.address,
        )
        db.add(supplier)
        db.flush()
        db.refresh(supplier)
        return supplier

    @staticmethod
    def update_supplier(
        db: Session, org_id: int, supplier_id: int, data: SupplierUpdate
    ) -> Supplier:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        update_data = data.model_dump(exclude_unset=True)

        if "name" in update_data and update_data["name"] != supplier.name:
            conflict = db.scalar(
                select(Supplier).where(
                    Supplier.organization_id == org_id,
                    Supplier.name == update_data["name"],
                    Supplier.id != supplier_id,
                )
            )
            if conflict:
                raise ConflictException(
                    detail=f"Supplier '{update_data['name']}' already exists"
                )

        for field, value in update_data.items():
            setattr(supplier, field, value)

        db.flush()
        db.refresh(supplier)
        return supplier

    @staticmethod
    def delete_supplier(db: Session, org_id: int, supplier_id: int) -> None:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        supplier.is_active = False
        db.flush()

    # ------------------------------------------------------------------
    # Supplier Products
    # ------------------------------------------------------------------
    @staticmethod
    def list_supplier_products(
        db: Session, org_id: int, supplier_id: int
    ) -> list[SupplierProductResponse]:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

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
        rows = db.execute(stmt).all()

        return [
            SupplierProductResponse(
                id=sp.id,
                supplier_id=sp.supplier_id,
                product_id=sp.product_id,
                cost_price=sp.cost_price,
                supplier_sku=sp.supplier_sku,
                product_name=product_name,
                product_sku=product_sku,
            )
            for sp, product_name, product_sku in rows
        ]

    @staticmethod
    def create_supplier_product(
        db: Session, org_id: int, supplier_id: int, data: SupplierProductCreate
    ) -> SupplierProduct:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        product = db.get(Product, data.product_id)
        if not product or product.organization_id != org_id or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")

        existing = db.scalar(
            select(SupplierProduct).where(
                SupplierProduct.supplier_id == supplier_id,
                SupplierProduct.product_id == data.product_id,
            )
        )
        if existing:
            raise ConflictException(
                detail="Product already linked to this supplier"
            )

        sp = SupplierProduct(
            supplier_id=supplier_id,
            product_id=data.product_id,
            cost_price=data.cost_price,
            supplier_sku=data.supplier_sku,
        )
        db.add(sp)
        db.flush()
        db.refresh(sp)
        return sp

    @staticmethod
    def update_supplier_product(
        db: Session, org_id: int, supplier_product_id: int, data: SupplierProductUpdate
    ) -> SupplierProduct:
        sp = db.get(SupplierProduct, supplier_product_id)
        if not sp:
            raise NotFoundException(detail="Supplier product link not found")

        supplier = db.get(Supplier, sp.supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(sp, field, value)

        db.flush()
        db.refresh(sp)
        return sp

    @staticmethod
    def delete_supplier_product(
        db: Session, org_id: int, supplier_product_id: int
    ) -> None:
        sp = db.get(SupplierProduct, supplier_product_id)
        if not sp:
            raise NotFoundException(detail="Supplier product link not found")

        supplier = db.get(Supplier, sp.supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        db.delete(sp)
        db.flush()

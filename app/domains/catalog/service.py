import datetime

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
from database.models import (
    Category,
    Product,
    Supplier,
    SupplierProduct,
)
from database.repositories.catalog import CatalogRepository
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
        categories = CatalogRepository.list_categories(db, org_id)
        return CategoryListResponse(
            categories=[CategoryResponse.model_validate(c) for c in categories],
            total=len(categories),
        )

    @staticmethod
    def create_category(db: Session, org_id: int, data: CategoryCreate) -> Category:
        existing = CatalogRepository.find_category_by_name(db, org_id, data.name)
        if existing:
            raise ConflictException(
                detail=f"Category '{data.name}' already exists"
            )

        if data.parent_id is not None:
            parent = CatalogRepository.get_category(db, data.parent_id)
            if not parent or parent.organization_id != org_id:
                raise NotFoundException(detail="Parent category not found")

        category = Category(
            organization_id=org_id,
            name=data.name,
            description=data.description,
            parent_id=data.parent_id,
            sort_order=data.sort_order,
        )
        CatalogRepository.add_category(db, category)
        db.refresh(category)
        return category

    @staticmethod
    def update_category(
        db: Session, org_id: int, category_id: int, data: CategoryUpdate
    ) -> Category:
        category = CatalogRepository.get_category(db, category_id)
        if not category or category.organization_id != org_id:
            raise NotFoundException(detail="Category not found")

        update_data = data.model_dump(exclude_unset=True)

        if "name" in update_data and update_data["name"] != category.name:
            conflict = CatalogRepository.find_category_name_conflict(
                db, org_id, category_id, update_data["name"]
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
            parent = CatalogRepository.get_category(db, update_data["parent_id"])
            if not parent or parent.organization_id != org_id:
                raise NotFoundException(detail="Parent category not found")

        for field, value in update_data.items():
            setattr(category, field, value)

        db.flush()
        db.refresh(category)
        return category

    @staticmethod
    def delete_category(db: Session, org_id: int, category_id: int) -> None:
        category = CatalogRepository.get_category(db, category_id)
        if not category or category.organization_id != org_id:
            raise NotFoundException(detail="Category not found")

        child_count = CatalogRepository.count_child_categories(db, org_id, category_id)
        if child_count and child_count > 0:
            raise BadRequestException(
                detail="Cannot delete category with subcategories"
            )

        product_count = CatalogRepository.count_category_products(db, org_id, category_id)
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
        search: str | None = None,
        category_id: int | None = None,
        is_active: bool | None = None,
    ) -> ProductListResponse:
        products, total = CatalogRepository.list_products(
            db, org_id, page, per_page, search, category_id, is_active
        )

        return ProductListResponse(
            products=[ProductResponse.model_validate(p) for p in products],
            total=total,
            page=page,
            per_page=per_page,
        )

    @staticmethod
    def get_product(db: Session, org_id: int, product_id: int) -> Product:
        product = CatalogRepository.get_product(db, product_id)
        if not product or product.organization_id != org_id or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")
        return product

    @staticmethod
    def create_product(db: Session, org_id: int, data: ProductCreate) -> Product:
        existing = CatalogRepository.find_by_sku(db, org_id, data.sku)
        if existing:
            raise ConflictException(
                detail=f"Product with SKU '{data.sku}' already exists"
            )

        if data.barcode:
            barcode_conflict = CatalogRepository.find_by_barcode(db, org_id, data.barcode)
            if barcode_conflict:
                raise ConflictException(
                    detail=f"Product with barcode '{data.barcode}' already exists"
                )

        if data.category_id is not None:
            category = CatalogRepository.get_category(db, data.category_id)
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
        CatalogRepository.add_product(db, product)
        db.refresh(product)
        return product

    @staticmethod
    def update_product(
        db: Session, org_id: int, product_id: int, data: ProductUpdate
    ) -> Product:
        product = CatalogRepository.get_product(db, product_id)
        if not product or product.organization_id != org_id or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")

        update_data = data.model_dump(exclude_unset=True)

        if "sku" in update_data and update_data["sku"] != product.sku:
            sku_conflict = CatalogRepository.find_sku_conflict(
                db, org_id, product_id, update_data["sku"]
            )
            if sku_conflict:
                raise ConflictException(
                    detail=f"Product with SKU '{update_data['sku']}' already exists"
                )

        if "barcode" in update_data and update_data["barcode"] and update_data["barcode"] != product.barcode:
            barcode_conflict = CatalogRepository.find_barcode_conflict(
                db, org_id, product_id, update_data["barcode"]
            )
            if barcode_conflict:
                raise ConflictException(
                    detail=f"Product with barcode '{update_data['barcode']}' already exists"
                )

        if "category_id" in update_data and update_data["category_id"] is not None:
            category = CatalogRepository.get_category(db, update_data["category_id"])
            if not category or category.organization_id != org_id:
                raise NotFoundException(detail="Category not found")

        for field, value in update_data.items():
            setattr(product, field, value)

        db.flush()
        db.refresh(product)
        return product

    @staticmethod
    def delete_product(db: Session, org_id: int, product_id: int) -> None:
        product = CatalogRepository.get_product(db, product_id)
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
        search: str | None = None,
    ) -> SupplierListResponse:
        suppliers, total = CatalogRepository.list_suppliers(db, org_id, page, per_page, search)

        return SupplierListResponse(
            suppliers=[SupplierResponse.model_validate(s) for s in suppliers],
            total=total,
            page=page,
            per_page=per_page,
        )

    @staticmethod
    def get_supplier(db: Session, org_id: int, supplier_id: int) -> Supplier:
        supplier = CatalogRepository.get_supplier(db, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")
        return supplier

    @staticmethod
    def create_supplier(db: Session, org_id: int, data: SupplierCreate) -> Supplier:
        existing = CatalogRepository.find_supplier_by_name(db, org_id, data.name)
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
        CatalogRepository.add_supplier(db, supplier)
        db.refresh(supplier)
        return supplier

    @staticmethod
    def update_supplier(
        db: Session, org_id: int, supplier_id: int, data: SupplierUpdate
    ) -> Supplier:
        supplier = CatalogRepository.get_supplier(db, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        update_data = data.model_dump(exclude_unset=True)

        if "name" in update_data and update_data["name"] != supplier.name:
            conflict = CatalogRepository.find_supplier_name_conflict(
                db, org_id, supplier_id, update_data["name"]
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
        supplier = CatalogRepository.get_supplier(db, supplier_id)
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
        supplier = CatalogRepository.get_supplier(db, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        rows = CatalogRepository.list_supplier_products(db, supplier_id)

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
        supplier = CatalogRepository.get_supplier(db, supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        product = CatalogRepository.get_product(db, data.product_id)
        if not product or product.organization_id != org_id or product.deleted_at is not None:
            raise NotFoundException(detail="Product not found")

        existing = CatalogRepository.find_supplier_product_link(db, supplier_id, data.product_id)
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
        CatalogRepository.add_supplier_product(db, sp)
        db.refresh(sp)
        return sp

    @staticmethod
    def update_supplier_product(
        db: Session, org_id: int, supplier_product_id: int, data: SupplierProductUpdate
    ) -> SupplierProduct:
        sp = CatalogRepository.get_supplier_product(db, supplier_product_id)
        if not sp:
            raise NotFoundException(detail="Supplier product link not found")

        supplier = CatalogRepository.get_supplier(db, sp.supplier_id)
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
        sp = CatalogRepository.get_supplier_product(db, supplier_product_id)
        if not sp:
            raise NotFoundException(detail="Supplier product link not found")

        supplier = CatalogRepository.get_supplier(db, sp.supplier_id)
        if not supplier or supplier.organization_id != org_id:
            raise NotFoundException(detail="Supplier not found")

        CatalogRepository.delete_supplier_product(db, sp)
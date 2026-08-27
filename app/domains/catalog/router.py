from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.database import get_db
from app.domains.catalog.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    SupplierCreate,
    SupplierProductCreate,
    SupplierProductResponse,
    SupplierProductUpdate,
    SupplierResponse,
    SupplierUpdate,
)
from app.domains.catalog.service import CatalogService
from app.middleware.auth import get_current_branch, require_permission
from database.models import User

router = APIRouter()


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.read")),
):
    result = CatalogService.list_categories(db, user.organization_id)
    return result.categories


@router.post("/categories", response_model=CategoryResponse, status_code=201)
def create_category(
    data: CategoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    return CatalogService.create_category(db, user.organization_id, data)


@router.put("/categories/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: int,
    data: CategoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    return CatalogService.update_category(db, user.organization_id, category_id, data)


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    CatalogService.delete_category(db, user.organization_id, category_id)
    return None


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@router.get("/products", response_model=list[ProductResponse])
def list_products(
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    category_id: int | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.read")),
):
    result = CatalogService.list_products(
        db, user.organization_id, page, per_page, search, category_id, is_active
    )
    return result.products


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.read")),
):
    return CatalogService.get_product(db, user.organization_id, product_id)


@router.post("/products", response_model=ProductResponse, status_code=201)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    return CatalogService.create_product(db, user.organization_id, data)


@router.put("/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    return CatalogService.update_product(db, user.organization_id, product_id, data)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    CatalogService.delete_product(db, user.organization_id, product_id)
    return None


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
@router.get("/suppliers", response_model=list[SupplierResponse])
def list_suppliers(
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.read")),
):
    result = CatalogService.list_suppliers(db, user.organization_id, page, per_page, search)
    return result.suppliers


@router.get("/suppliers/{supplier_id}", response_model=SupplierResponse)
def get_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.read")),
):
    return CatalogService.get_supplier(db, user.organization_id, supplier_id)


@router.post("/suppliers", response_model=SupplierResponse, status_code=201)
def create_supplier(
    data: SupplierCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    return CatalogService.create_supplier(db, user.organization_id, data)


@router.put("/suppliers/{supplier_id}", response_model=SupplierResponse)
def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    return CatalogService.update_supplier(db, user.organization_id, supplier_id, data)


@router.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    CatalogService.delete_supplier(db, user.organization_id, supplier_id)
    return None


# ---------------------------------------------------------------------------
# Supplier Products
# ---------------------------------------------------------------------------
@router.get(
    "/suppliers/{supplier_id}/products",
    response_model=list[SupplierProductResponse],
)
def list_supplier_products(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.read")),
):
    return CatalogService.list_supplier_products(db, user.organization_id, supplier_id)


@router.post(
    "/suppliers/{supplier_id}/products",
    response_model=SupplierProductResponse,
    status_code=201,
)
def create_supplier_product(
    supplier_id: int,
    data: SupplierProductCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    return CatalogService.create_supplier_product(
        db, user.organization_id, supplier_id, data
    )


@router.put(
    "/suppliers/{supplier_id}/products/{supplier_product_id}",
    response_model=SupplierProductResponse,
)
def update_supplier_product(
    supplier_id: int,
    supplier_product_id: int,
    data: SupplierProductUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    return CatalogService.update_supplier_product(
        db, user.organization_id, supplier_product_id, data
    )


@router.delete(
    "/suppliers/{supplier_id}/products/{supplier_product_id}",
    status_code=204,
)
def delete_supplier_product(
    supplier_id: int,
    supplier_product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("catalog.create")),
):
    CatalogService.delete_supplier_product(
        db, user.organization_id, supplier_product_id
    )
    return None

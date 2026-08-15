from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product
from app.schemas import ProductCreate, ProductUpdate, ProductResponse

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("/", response_model=list[ProductResponse])
def get_products(
    skip: int = Query(default=0, ge=0, description="จำนวนรายการที่ข้าม"),
    limit: int = Query(default=20, ge=1, le=100, description="จำนวนรายการสูงสุดที่คืน"),
    db: Session = Depends(get_db),
):
    """ดึงรายการสินค้าทั้งหมด (รองรับ pagination)"""
    products = db.query(Product).offset(skip).limit(limit).all()
    return products


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """ดึงข้อมูลสินค้าตาม ID"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product id {product_id} not found",
        )
    return product


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    """สร้างสินค้าใหม่"""
    product = Product(
        name=payload.name,
        description=payload.description,
        price=payload.price,
        stock=payload.stock,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    """อัปเดตข้อมูลสินค้าตาม ID"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product id {product_id} not found",
        )
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}/stock", response_model=ProductResponse)
def update_stock(
    product_id: int,
    quantity: int = Query(..., description="จำนวนที่ต้องการเพิ่ม (+) หรือลด (-) ใน stock"),
    db: Session = Depends(get_db),
):
    """ปรับจำนวน stock ของสินค้า (บวก/ลบ)"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product id {product_id} not found",
        )
    new_stock = product.stock + quantity
    if new_stock < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Current stock: {product.stock}, requested change: {quantity}",
        )
    product.stock = new_stock
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    """ลบสินค้าตาม ID"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product id {product_id} not found",
        )
    db.delete(product)
    db.commit()

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 1. Organization
# ---------------------------------------------------------------------------
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# 2. Branch
# ---------------------------------------------------------------------------
class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_branch_org_code"),
        UniqueConstraint("organization_id", "name", name="uq_branch_org_name"),
        Index("ix_branches_org", "organization_id"),
    )

    users: Mapped[list["User"]] = relationship("User", secondary="user_roles", viewonly=True)


# ---------------------------------------------------------------------------
# 3. User
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("organization_id", "username", name="uq_user_org_username"),
        UniqueConstraint("organization_id", "email", name="uq_user_org_email"),
        Index(
            "ix_users_org_active",
            "organization_id",
            postgresql_where="deleted_at IS NULL",
        ),
        CheckConstraint("status IN ('active', 'inactive', 'locked')", name="ck_user_status"),
    )

    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# 4. Role
# ---------------------------------------------------------------------------
class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_role_org_name"),
    )

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )
    permissions: Mapped[list["Permission"]] = relationship(
        "Permission", secondary="role_permissions", back_populates="roles", viewonly=True
    )
    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole", back_populates="role"
    )


# ---------------------------------------------------------------------------
# 5. Permission
# ---------------------------------------------------------------------------
class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    roles: Mapped[list["Role"]] = relationship(
        "Role", secondary="role_permissions", back_populates="permissions", viewonly=True
    )


# ---------------------------------------------------------------------------
# 6. RolePermission
# ---------------------------------------------------------------------------
class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship("Permission")


# ---------------------------------------------------------------------------
# 7. UserRole
# ---------------------------------------------------------------------------
class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "branch_id", name="uq_user_role_branch"),
    )

    user: Mapped["User"] = relationship("User", back_populates="user_roles")
    role: Mapped["Role"] = relationship("Role", back_populates="user_roles")


# ---------------------------------------------------------------------------
# 8. Category
# ---------------------------------------------------------------------------
class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_category_org_name"),
    )


# ---------------------------------------------------------------------------
# 9. Product
# ---------------------------------------------------------------------------
class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(255))
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, server_default="each")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    has_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_product_org_sku"),
        Index(
            "uq_product_org_barcode",
            "organization_id",
            "barcode",
            unique=True,
            postgresql_where="barcode IS NOT NULL",
        ),
        CheckConstraint("selling_price > 0", name="ck_product_selling_price_positive"),
        CheckConstraint("cost_price >= 0", name="ck_product_cost_price_non_negative"),
        Index(
            "ix_products_org_active",
            "organization_id",
            postgresql_where="deleted_at IS NULL",
        ),
    )


# ---------------------------------------------------------------------------
# 10. Supplier
# ---------------------------------------------------------------------------
class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# 11. SupplierProduct
# ---------------------------------------------------------------------------
class SupplierProduct(Base):
    __tablename__ = "supplier_products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    supplier_sku: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("supplier_id", "product_id", name="uq_supplier_product"),
    )


# ---------------------------------------------------------------------------
# 12. Inventory
# ---------------------------------------------------------------------------
class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("branch_id", "product_id", name="uq_inventory_branch_product"),
        CheckConstraint("on_hand >= 0", name="ck_inventory_on_hand_non_negative"),
        CheckConstraint("reserved >= 0", name="ck_inventory_reserved_non_negative"),
        CheckConstraint("reserved <= on_hand", name="ck_inventory_reserved_lte_on_hand"),
        Index(
            "ix_inventory_low_stock",
            "branch_id",
            "product_id",
            postgresql_where="on_hand <= 10",
        ),
    )


# ---------------------------------------------------------------------------
# 13. InventoryLot
# ---------------------------------------------------------------------------
class InventoryLot(Base):
    __tablename__ = "inventory_lots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    lot_number: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expiry_date: Mapped[datetime.date | None] = mapped_column(Date)
    purchase_receiving_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("purchase_receivings.id", ondelete="SET NULL")
    )
    stock_transfer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("stock_transfers.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("branch_id", "product_id", "lot_number", name="uq_inventory_lot"),
        CheckConstraint("quantity >= 0", name="ck_inventory_lot_quantity_non_negative"),
        Index(
            "ix_inventory_lot_fefo",
            "branch_id",
            "product_id",
            "expiry_date",
        ),
    )


# ---------------------------------------------------------------------------
# 14. StockMovement
# ---------------------------------------------------------------------------
class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    movement_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_before: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50))
    reference_id: Mapped[int | None] = mapped_column(BigInteger)
    lot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inventory_lots.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("quantity_change != 0", name="ck_stock_movement_quantity_nonzero"),
        CheckConstraint("quantity_before >= 0", name="ck_stock_movement_before_non_negative"),
        CheckConstraint("quantity_after >= 0", name="ck_stock_movement_after_non_negative"),
        CheckConstraint(
            "quantity_after = quantity_before + quantity_change",
            name="ck_stock_movement_math_correct",
        ),
        Index("ix_stock_movement_branch_product", "branch_id", "product_id"),
        Index("ix_stock_movement_reference", "reference_type", "reference_id"),
        Index("ix_stock_movement_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# 15. PurchaseOrder
# ---------------------------------------------------------------------------
class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    po_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    expected_delivery_date: Mapped[datetime.date | None] = mapped_column(Date)
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_order_status",
        ),
    )


# ---------------------------------------------------------------------------
# 16. PurchaseOrderItem
# ---------------------------------------------------------------------------
class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ck_po_item_qty_ordered_positive"),
        CheckConstraint("quantity_received >= 0", name="ck_po_item_qty_received_non_negative"),
        CheckConstraint(
            "quantity_received <= quantity_ordered",
            name="ck_po_item_qty_received_lte_ordered",
        ),
        CheckConstraint("unit_cost >= 0", name="ck_po_item_unit_cost_non_negative"),
    )


# ---------------------------------------------------------------------------
# 17. PurchaseReceiving
# ---------------------------------------------------------------------------
class PurchaseReceiving(Base):
    __tablename__ = "purchase_receivings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    receiving_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    received_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    received_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 18. PurchaseReceivingItem
# ---------------------------------------------------------------------------
class PurchaseReceivingItem(Base):
    __tablename__ = "purchase_receiving_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    purchase_receiving_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_receivings.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    lot_number: Mapped[str] = mapped_column(String(100), nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expiry_date: Mapped[datetime.date | None] = mapped_column(Date)
    inventory_lot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inventory_lots.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint("quantity_received > 0", name="ck_pr_item_qty_received_positive"),
    )


# ---------------------------------------------------------------------------
# 19. StockTransfer
# ---------------------------------------------------------------------------
class StockTransfer(Base):
    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    source_branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    dest_branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    transfer_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    shipped_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    received_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    requested_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["StockTransferItem"]] = relationship(
        "StockTransferItem", back_populates="transfer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("source_branch_id != dest_branch_id", name="ck_transfer_different_branches"),
        CheckConstraint(
            "status IN ('draft', 'approved', 'in_transit', 'partially_received', 'received', 'cancelled')",
            name="ck_stock_transfer_status",
        ),
    )


# ---------------------------------------------------------------------------
# 20. StockTransferItem
# ---------------------------------------------------------------------------
class StockTransferItem(Base):
    __tablename__ = "stock_transfer_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_transfer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_shipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    quantity_damaged: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inventory_lots.id", ondelete="SET NULL")
    )

    transfer: Mapped["StockTransfer"] = relationship("StockTransfer", back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity_requested > 0", name="ck_transfer_item_requested_positive"),
        CheckConstraint("quantity_shipped >= 0", name="ck_transfer_item_shipped_non_negative"),
        CheckConstraint("quantity_received >= 0", name="ck_transfer_item_received_non_negative"),
        CheckConstraint("quantity_damaged >= 0", name="ck_transfer_item_damaged_non_negative"),
        CheckConstraint(
            "quantity_shipped <= quantity_requested",
            name="ck_transfer_item_shipped_lte_requested",
        ),
        CheckConstraint(
            "quantity_received + quantity_damaged <= quantity_shipped",
            name="ck_transfer_item_received_damaged_lte_shipped",
        ),
    )


# ---------------------------------------------------------------------------
# 21. Customer
# ---------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    date_of_birth: Mapped[datetime.date | None] = mapped_column(Date)
    loyalty_points_balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_customer_org_phone",
            "organization_id",
            "phone",
            unique=True,
            postgresql_where="phone IS NOT NULL",
        ),
        Index(
            "ix_customers_org_active",
            "organization_id",
            postgresql_where="deleted_at IS NULL",
        ),
    )


# ---------------------------------------------------------------------------
# 22. LoyaltyTransaction
# ---------------------------------------------------------------------------
class LoyaltyTransaction(Base):
    __tablename__ = "loyalty_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    points_before: Mapped[int] = mapped_column(Integer, nullable=False)
    points_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50))
    reference_id: Mapped[int | None] = mapped_column(BigInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('earn', 'redeem', 'expire', 'adjustment', 'refund_reversal')",
            name="ck_loyalty_txn_type",
        ),
        CheckConstraint("points != 0", name="ck_loyalty_txn_points_nonzero"),
        CheckConstraint("points_before >= 0", name="ck_loyalty_txn_before_non_negative"),
        CheckConstraint("points_after >= 0", name="ck_loyalty_txn_after_non_negative"),
        CheckConstraint(
            "points_after = points_before + points",
            name="ck_loyalty_txn_math_correct",
        ),
        Index("ix_loyalty_txn_customer_created", "customer_id", "created_at"),
        Index(
            "ix_loyalty_txn_customer_expires",
            "customer_id",
            "expires_at",
            postgresql_where="expires_at IS NOT NULL",
        ),
    )


# ---------------------------------------------------------------------------
# 23. Order
# ---------------------------------------------------------------------------
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    order_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="SET NULL")
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    shift_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shifts.id", ondelete="SET NULL")
    )
    register_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("registers.id", ondelete="SET NULL")
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    grand_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    change_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    loyalty_points_earned: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    loyalty_points_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'preparing', 'ready', 'completed', 'cancelled')",
            name="ck_order_status",
        ),
        Index("ix_orders_branch_created", "branch_id", "created_at"),
        Index("ix_orders_status", "status"),
        Index(
            "uq_orders_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
    )


# ---------------------------------------------------------------------------
# 24. OrderItem
# ---------------------------------------------------------------------------
class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    promotion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order: Mapped["Order"] = relationship("Order", back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_order_item_unit_price_non_negative"),
        CheckConstraint("line_total >= 0", name="ck_order_item_line_total_non_negative"),
    )


# ---------------------------------------------------------------------------
# 25. Payment
# ---------------------------------------------------------------------------
class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    external_reference: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str | None] = mapped_column(String(50))
    received_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'refunded')",
            name="ck_payment_status",
        ),
        CheckConstraint(
            "payment_method IN ('cash', 'credit_card', 'debit_card', 'qr_code', 'bank_transfer', 'e_wallet')",
            name="ck_payment_method",
        ),
    )


# ---------------------------------------------------------------------------
# 26. Refund
# ---------------------------------------------------------------------------
class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    refund_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    refund_method: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    processed_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    external_reference: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("refund_amount > 0", name="ck_refund_amount_positive"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_refund_status",
        ),
    )


# ---------------------------------------------------------------------------
# 27. Return
# ---------------------------------------------------------------------------
class Return(Base):
    __tablename__ = "returns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    return_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    refund_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("refunds.id", ondelete="SET NULL")
    )
    processed_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["ReturnItem"]] = relationship(
        "ReturnItem", back_populates="return_record", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled')",
            name="ck_return_status",
        ),
    )


# ---------------------------------------------------------------------------
# 28. ReturnItem
# ---------------------------------------------------------------------------
class ReturnItem(Base):
    __tablename__ = "return_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("returns.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    return_reason: Mapped[str | None] = mapped_column(Text)
    restock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    return_record: Mapped["Return"] = relationship("Return", back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_return_item_quantity_positive"),
    )


# ---------------------------------------------------------------------------
# 29. Promotion
# ---------------------------------------------------------------------------
class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    promotion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    minimum_purchase: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    start_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "promotion_type IN ('percentage_discount', 'fixed_discount', 'buy_x_get_y', 'free_item', 'min_purchase_discount')",
            name="ck_promotion_type",
        ),
        CheckConstraint("end_date > start_date", name="ck_promotion_date_range"),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_promotion_max_uses"),
        Index(
            "ix_promotions_active",
            "organization_id",
            "start_date",
            "end_date",
            postgresql_where="is_active = true",
        ),
    )


# ---------------------------------------------------------------------------
# 30. PromotionBranch (replaces promotions.branch_ids ARRAY)
# ---------------------------------------------------------------------------
class PromotionBranch(Base):
    __tablename__ = "promotion_branches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("promotion_id", "branch_id", name="uq_promotion_branch"),
    )


# ---------------------------------------------------------------------------
# 31. PromotionRule (buy X get Y, free item, etc.)
# ---------------------------------------------------------------------------
class PromotionRule(Base):
    __tablename__ = "promotion_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="CASCADE"), nullable=False
    )
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('buy', 'get', 'condition')",
            name="ck_promotion_rule_type",
        ),
        CheckConstraint(
            "target_type IN ('product', 'category', 'any')",
            name="ck_promotion_rule_target_type",
        ),
        CheckConstraint("quantity > 0", name="ck_promotion_rule_quantity_positive"),
    )


# ---------------------------------------------------------------------------
# 32. Coupon
# ---------------------------------------------------------------------------
class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    promotion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="RESTRICT"), nullable=False
    )
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_uses_per_customer: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    start_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_coupon_org_code"),
        CheckConstraint("end_date > start_date", name="ck_coupon_date_range"),
    )


# ---------------------------------------------------------------------------
# 33. CouponUsage
# ---------------------------------------------------------------------------
class CouponUsage(Base):
    __tablename__ = "coupon_usages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    coupon_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("coupons.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 34. Register
# ---------------------------------------------------------------------------
class Register(Base):
    __tablename__ = "registers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("branch_id", "name", name="uq_register_branch_name"),
    )


# ---------------------------------------------------------------------------
# 35. Shift
# ---------------------------------------------------------------------------
class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    register_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("registers.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="open")
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    closing_cash: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    expected_cash: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    cash_difference: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total_cash_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total_card_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total_other_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total_refunds: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    closed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    opened_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('open', 'closed')", name="ck_shift_status"),
        Index("ix_shifts_branch_status", "branch_id", "status"),
    )


# ---------------------------------------------------------------------------
# 36. ShiftCashMovement
# ---------------------------------------------------------------------------
class ShiftCashMovement(Base):
    __tablename__ = "shift_cash_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shift_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False
    )
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_shift_cash_movement_amount_positive"),
        CheckConstraint(
            "movement_type IN ('cash_in', 'cash_out')",
            name="ck_shift_cash_movement_type",
        ),
    )


# ---------------------------------------------------------------------------
# 37. SystemSetting
# ---------------------------------------------------------------------------
class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT")
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="string")
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "branch_id", "key",
            name="uq_system_setting_org_branch_key",
        ),
    )


# ---------------------------------------------------------------------------
# 38. AuditLog
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL")
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    before_data: Mapped[dict | None] = mapped_column(JSONB)
    after_data: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(255))
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_log_org_created", "organization_id", "created_at"),
        Index("ix_audit_log_user_created", "user_id", "created_at"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )


# ---------------------------------------------------------------------------
# 39. IdempotencyKey
# ---------------------------------------------------------------------------
class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", "endpoint", name="uq_idempotency_key_endpoint"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )


# ---------------------------------------------------------------------------
# 40. RefreshToken
# ---------------------------------------------------------------------------
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    device_info: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_refresh_tokens_valid",
            "user_id",
            "expires_at",
            postgresql_where="is_revoked = false",
        ),
    )


# ---------------------------------------------------------------------------
# 41. LoginAttempt
# ---------------------------------------------------------------------------
class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    attempted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_login_attempts_username_time", "username", "attempted_at"),
        Index("ix_login_attempts_ip_time", "ip_address", "attempted_at"),
    )


# ---------------------------------------------------------------------------
# 42. DocumentSequence
# ---------------------------------------------------------------------------
class DocumentSequence(Base):
    __tablename__ = "document_sequences"

    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sequence_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        PrimaryKeyConstraint("doc_type", "sequence_date", name="pk_document_sequence"),
    )


# ---------------------------------------------------------------------------
# 43. PaymentVerification (Slip Verification)
# ---------------------------------------------------------------------------
class PaymentVerification(Base):
    __tablename__ = "payment_verifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    payment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="SET NULL")
    )

    # OCR extracted data
    ocr_raw_texts: Mapped[dict | None] = mapped_column(JSONB)
    ocr_bank: Mapped[str | None] = mapped_column(String(50))
    ocr_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ocr_reference: Mapped[str | None] = mapped_column(String(255))
    ocr_date: Mapped[datetime.date | None] = mapped_column(Date)
    ocr_time: Mapped[datetime.time | None] = mapped_column(DateTime)
    ocr_sender_name: Mapped[str | None] = mapped_column(String(255))
    ocr_receiver_name: Mapped[str | None] = mapped_column(String(255))
    ocr_sender_account: Mapped[str | None] = mapped_column(String(50))
    ocr_receiver_account: Mapped[str | None] = mapped_column(String(50))
    ocr_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ocr_status_text: Mapped[str | None] = mapped_column(String(100))
    ocr_field_confidences: Mapped[dict | None] = mapped_column(JSONB)

    # Image metadata
    image_storage_key: Mapped[str | None] = mapped_column(String(500))
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image_perceptual_hash: Mapped[str | None] = mapped_column(String(64))
    image_mime_type: Mapped[str | None] = mapped_column(String(50))
    image_file_size: Mapped[int | None] = mapped_column(Integer)

    # Verification result
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    risk_score: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    risk_signals: Mapped[dict | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # Audit
    verified_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    order: Mapped["Order"] = relationship("Order", foreign_keys=[order_id])
    payment: Mapped["Payment | None"] = relationship("Payment", foreign_keys=[payment_id])
    created_by_user: Mapped["User"] = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'review', 'amount_mismatch', "
            "'duplicate_reference', 'duplicate_image', 'order_not_found', 'order_already_paid', "
            "'ocr_failed', 'receiver_mismatch')",
            name="ck_verification_status",
        ),
    )


# ---------------------------------------------------------------------------
# 44.1 WineProduct (reference catalog from Open Food Facts)
# ---------------------------------------------------------------------------
class WineProduct(Base):
    __tablename__ = "wine_products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    product_name: Mapped[str | None] = mapped_column(String(500))
    brands: Mapped[str | None] = mapped_column(String(255))
    categories_en: Mapped[str | None] = mapped_column(Text)
    origins_en: Mapped[str | None] = mapped_column(Text)
    countries_en: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[str | None] = mapped_column(String(100))
    ingredients_text: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    image_small_url: Mapped[str | None] = mapped_column(Text)
    alcohol_100g: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_wine_products_name", "product_name"),
        Index("ix_wine_products_brands", "brands"),
    )


# ---------------------------------------------------------------------------
# 45. VerificationAttempt (Audit Trail)
# ---------------------------------------------------------------------------
class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    verification_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("payment_verifications.id", ondelete="SET NULL")
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="SET NULL")
    )

    # Request info
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    # Input snapshot
    image_sha256: Mapped[str | None] = mapped_column(String(64))
    ocr_reference: Mapped[str | None] = mapped_column(String(255))
    ocr_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Result
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    risk_score: Mapped[dict | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

"""initial schema - all 42 tables (Phase 6)

Revision ID: 001_initial
Revises:
Create Date: 2026-08-18 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # Domain: Identity & Organization
    # =========================================================================

    # 1. organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    # 2. branches
    op.create_table(
        "branches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "code", name="uq_branch_org_code"),
        sa.UniqueConstraint("organization_id", "name", name="uq_branch_org_name"),
    )
    op.create_index("ix_branches_org", "branches", ["organization_id"])

    # 3. users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "username", name="uq_user_org_username"),
        sa.UniqueConstraint("organization_id", "email", name="uq_user_org_email"),
        sa.CheckConstraint("status IN ('active', 'inactive', 'locked')", name="ck_user_status"),
    )
    op.create_index(
        "ix_users_org_active", "users", ["organization_id"],
        postgresql_where="deleted_at IS NULL",
    )

    # 4. roles
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "name", name="uq_role_org_name"),
    )

    # 5. permissions
    op.create_table(
        "permissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("module", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    # 6. role_permissions
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    # 7. user_roles
    op.create_table(
        "user_roles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("user_id", "role_id", "branch_id", name="uq_user_role_branch"),
    )

    # 8. refresh_tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("device_info", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_refresh_tokens_valid", "refresh_tokens", ["user_id", "expires_at"],
        postgresql_where="is_revoked = false",
    )

    # 9. login_attempts
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_login_attempts_username_time", "login_attempts", ["username", "attempted_at"])
    op.create_index("ix_login_attempts_ip_time", "login_attempts", ["ip_address", "attempted_at"])

    # =========================================================================
    # Domain: Catalog
    # =========================================================================

    # 10. categories
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "name", name="uq_category_org_name"),
    )

    # 11. products
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("barcode", sa.String(255), nullable=True),
        sa.Column("selling_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(20), nullable=False, server_default="each"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("track_inventory", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("has_expiry", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "sku", name="uq_product_org_sku"),
        sa.CheckConstraint("selling_price > 0", name="ck_product_selling_price_positive"),
        sa.CheckConstraint("cost_price >= 0", name="ck_product_cost_price_non_negative"),
    )
    op.create_index(
        "uq_product_org_barcode", "products", ["organization_id", "barcode"],
        unique=True, postgresql_where="barcode IS NOT NULL",
    )
    op.create_index(
        "ix_products_org_active", "products", ["organization_id"],
        postgresql_where="deleted_at IS NULL",
    )

    # 12. suppliers
    op.create_table(
        "suppliers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )

    # 13. supplier_products
    op.create_table(
        "supplier_products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("supplier_sku", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("supplier_id", "product_id", name="uq_supplier_product"),
    )

    # =========================================================================
    # Domain: POS / Registers
    # =========================================================================

    # 14. registers
    op.create_table(
        "registers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("branch_id", "name", name="uq_register_branch_name"),
    )

    # =========================================================================
    # Domain: Inventory
    # =========================================================================

    # 15. inventory
    op.create_table(
        "inventory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("branch_id", "product_id", name="uq_inventory_branch_product"),
        sa.CheckConstraint("on_hand >= 0", name="ck_inventory_on_hand_non_negative"),
        sa.CheckConstraint("reserved >= 0", name="ck_inventory_reserved_non_negative"),
        sa.CheckConstraint("reserved <= on_hand", name="ck_inventory_reserved_lte_on_hand"),
    )
    op.create_index(
        "ix_inventory_low_stock", "inventory", ["branch_id", "product_id"],
        postgresql_where="on_hand <= 10",
    )

    # 16. inventory_lots
    op.create_table(
        "inventory_lots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_number", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("purchase_receiving_id", sa.BigInteger(), nullable=True),
        sa.Column("stock_transfer_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("branch_id", "product_id", "lot_number", name="uq_inventory_lot"),
        sa.CheckConstraint("quantity >= 0", name="ck_inventory_lot_quantity_non_negative"),
    )
    # FEFO index - created after purchase_receivings and stock_transfers tables exist
    # (added via create_index later)

    # 17. document_sequences
    op.create_table(
        "document_sequences",
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("sequence_date", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("doc_type", "sequence_date", name="pk_document_sequence"),
    )

    # =========================================================================
    # Domain: Stock Movements
    # =========================================================================

    # 18. stock_movements
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("movement_type", sa.String(50), nullable=False),
        sa.Column("quantity_change", sa.Integer(), nullable=False),
        sa.Column("quantity_before", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", sa.BigInteger(), nullable=True),
        sa.Column("lot_id", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lot_id"], ["inventory_lots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("quantity_change != 0", name="ck_stock_movement_quantity_nonzero"),
        sa.CheckConstraint("quantity_before >= 0", name="ck_stock_movement_before_non_negative"),
        sa.CheckConstraint("quantity_after >= 0", name="ck_stock_movement_after_non_negative"),
        sa.CheckConstraint(
            "quantity_after = quantity_before + quantity_change",
            name="ck_stock_movement_math_correct",
        ),
    )
    op.create_index("ix_stock_movement_branch_product", "stock_movements", ["branch_id", "product_id"])
    op.create_index("ix_stock_movement_reference", "stock_movements", ["reference_type", "reference_id"])
    op.create_index("ix_stock_movement_created_at", "stock_movements", ["created_at"])

    # =========================================================================
    # Domain: Purchasing
    # =========================================================================

    # 19. purchase_orders
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("po_number", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("po_number"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_order_status",
        ),
    )

    # 20. purchase_order_items
    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("purchase_order_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_ordered", sa.Integer(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("quantity_ordered > 0", name="ck_po_item_qty_ordered_positive"),
        sa.CheckConstraint("quantity_received >= 0", name="ck_po_item_qty_received_non_negative"),
        sa.CheckConstraint("quantity_received <= quantity_ordered", name="ck_po_item_qty_received_lte_ordered"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_po_item_unit_cost_non_negative"),
    )

    # 21. purchase_receivings
    op.create_table(
        "purchase_receivings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("purchase_order_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("receiving_number", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("received_by", sa.BigInteger(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("receiving_number"),
    )

    # 22. purchase_receiving_items
    op.create_table(
        "purchase_receiving_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("purchase_receiving_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("lot_number", sa.String(100), nullable=False),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("inventory_lot_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["purchase_receiving_id"], ["purchase_receivings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_lot_id"], ["inventory_lots.id"], ondelete="SET NULL"),
        sa.CheckConstraint("quantity_received > 0", name="ck_pr_item_qty_received_positive"),
    )

    # =========================================================================
    # Domain: Stock Transfers
    # =========================================================================

    # 23. stock_transfers
    op.create_table(
        "stock_transfers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("source_branch_id", sa.BigInteger(), nullable=False),
        sa.Column("dest_branch_id", sa.BigInteger(), nullable=False),
        sa.Column("transfer_number", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("shipped_by", sa.BigInteger(), nullable=True),
        sa.Column("received_by", sa.BigInteger(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dest_branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipped_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("transfer_number"),
        sa.CheckConstraint("source_branch_id != dest_branch_id", name="ck_transfer_different_branches"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'in_transit', 'partially_received', 'received', 'cancelled')",
            name="ck_stock_transfer_status",
        ),
    )

    # 24. stock_transfer_items
    op.create_table(
        "stock_transfer_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stock_transfer_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_requested", sa.Integer(), nullable=False),
        sa.Column("quantity_shipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity_damaged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lot_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["stock_transfer_id"], ["stock_transfers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lot_id"], ["inventory_lots.id"], ondelete="SET NULL"),
        sa.CheckConstraint("quantity_requested > 0", name="ck_transfer_item_requested_positive"),
        sa.CheckConstraint("quantity_shipped >= 0", name="ck_transfer_item_shipped_non_negative"),
        sa.CheckConstraint("quantity_received >= 0", name="ck_transfer_item_received_non_negative"),
        sa.CheckConstraint("quantity_damaged >= 0", name="ck_transfer_item_damaged_non_negative"),
        sa.CheckConstraint("quantity_shipped <= quantity_requested", name="ck_transfer_item_shipped_lte_requested"),
        sa.CheckConstraint(
            "quantity_received + quantity_damaged <= quantity_shipped",
            name="ck_transfer_item_received_damaged_lte_shipped",
        ),
    )

    # Now add the FEFO index for inventory_lots (after stock_transfers exists)
    op.create_index(
        "ix_inventory_lot_fefo", "inventory_lots", ["branch_id", "product_id", "expiry_date"],
    )

    # =========================================================================
    # Domain: Customers & Loyalty
    # =========================================================================

    # 25. customers
    op.create_table(
        "customers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(255), nullable=False),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("loyalty_points_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "uq_customer_org_phone", "customers", ["organization_id", "phone"],
        unique=True, postgresql_where="phone IS NOT NULL",
    )
    op.create_index(
        "ix_customers_org_active", "customers", ["organization_id"],
        postgresql_where="deleted_at IS NULL",
    )

    # 26. loyalty_transactions
    op.create_table(
        "loyalty_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("transaction_type", sa.String(30), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("points_before", sa.Integer(), nullable=False),
        sa.Column("points_after", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "transaction_type IN ('earn', 'redeem', 'expire', 'adjustment', 'refund_reversal')",
            name="ck_loyalty_txn_type",
        ),
        sa.CheckConstraint("points != 0", name="ck_loyalty_txn_points_nonzero"),
        sa.CheckConstraint("points_before >= 0", name="ck_loyalty_txn_before_non_negative"),
        sa.CheckConstraint("points_after >= 0", name="ck_loyalty_txn_after_non_negative"),
        sa.CheckConstraint("points_after = points_before + points", name="ck_loyalty_txn_math_correct"),
    )
    op.create_index("ix_loyalty_txn_customer_created", "loyalty_transactions", ["customer_id", "created_at"])
    op.create_index(
        "ix_loyalty_txn_customer_expires", "loyalty_transactions", ["customer_id", "expires_at"],
        postgresql_where="expires_at IS NOT NULL",
    )

    # =========================================================================
    # Domain: POS / Shifts
    # =========================================================================

    # 27. shifts
    op.create_table(
        "shifts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("register_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("opening_cash", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("closing_cash", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_cash", sa.Numeric(12, 2), nullable=True),
        sa.Column("cash_difference", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_sales", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_cash_sales", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_card_sales", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_other_sales", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_refunds", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("closed_by", sa.BigInteger(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["register_id"], ["registers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_shift_status"),
    )
    op.create_index("ix_shifts_branch_status", "shifts", ["branch_id", "status"])

    # 28. shift_cash_movements
    op.create_table(
        "shift_cash_movements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=False),
        sa.Column("movement_type", sa.String(30), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("amount > 0", name="ck_shift_cash_movement_amount_positive"),
        sa.CheckConstraint("movement_type IN ('cash_in', 'cash_out')", name="ck_shift_cash_movement_type"),
    )

    # =========================================================================
    # Domain: Promotions
    # =========================================================================

    # 29. promotions
    op.create_table(
        "promotions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("promotion_type", sa.String(50), nullable=False),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("minimum_purchase", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "promotion_type IN ('percentage_discount', 'fixed_discount', 'buy_x_get_y', 'free_item', 'min_purchase_discount')",
            name="ck_promotion_type",
        ),
        sa.CheckConstraint("end_date > start_date", name="ck_promotion_date_range"),
        sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_promotion_max_uses"),
    )
    op.create_index(
        "ix_promotions_active", "promotions", ["organization_id", "start_date", "end_date"],
        postgresql_where="is_active = true",
    )

    # 30. promotion_branches (NEW - replaces branch_ids ARRAY)
    op.create_table(
        "promotion_branches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["promotion_id"], ["promotions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("promotion_id", "branch_id", name="uq_promotion_branch"),
    )

    # 31. promotion_rules (NEW - buy X get Y support)
    op.create_table(
        "promotion_rules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_type", sa.String(30), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["promotion_id"], ["promotions.id"], ondelete="CASCADE"),
        sa.CheckConstraint("rule_type IN ('buy', 'get', 'condition')", name="ck_promotion_rule_type"),
        sa.CheckConstraint("target_type IN ('product', 'category', 'any')", name="ck_promotion_rule_target_type"),
        sa.CheckConstraint("quantity > 0", name="ck_promotion_rule_quantity_positive"),
    )

    # 32. coupons
    op.create_table(
        "coupons",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_uses_per_customer", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["promotion_id"], ["promotions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "code", name="uq_coupon_org_code"),
        sa.CheckConstraint("end_date > start_date", name="ck_coupon_date_range"),
    )

    # =========================================================================
    # Domain: Sales
    # =========================================================================

    # 33. orders
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("order_number", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=True),
        sa.Column("register_id", sa.BigInteger(), nullable=True),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("amount_paid", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("change_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("loyalty_points_earned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loyalty_points_redeemed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["register_id"], ["registers.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("order_number"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'cancelled')", name="ck_order_status"),
    )
    op.create_index("ix_orders_branch_created", "orders", ["branch_id", "created_at"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index(
        "uq_orders_idempotency_key", "orders", ["idempotency_key"],
        unique=True, postgresql_where="idempotency_key IS NOT NULL",
    )

    # 34. order_items
    op.create_table(
        "order_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("product_sku", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("promotion_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["promotion_id"], ["promotions.id"], ondelete="SET NULL"),
        sa.CheckConstraint("quantity > 0", name="ck_order_item_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_order_item_unit_price_non_negative"),
        sa.CheckConstraint("line_total >= 0", name="ck_order_item_line_total_non_negative"),
    )

    # =========================================================================
    # Domain: Payments
    # =========================================================================

    # 35. payments
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_method", sa.String(30), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("external_reference", sa.String(255), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("received_by", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed', 'refunded')", name="ck_payment_status"),
        sa.CheckConstraint(
            "payment_method IN ('cash', 'credit_card', 'debit_card', 'qr_code', 'bank_transfer', 'e_wallet')",
            name="ck_payment_method",
        ),
    )

    # =========================================================================
    # Domain: Returns & Refunds
    # =========================================================================

    # 36. refunds
    op.create_table(
        "refunds",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("refund_number", sa.String(50), nullable=False),
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("refund_method", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("processed_by", sa.BigInteger(), nullable=False),
        sa.Column("external_reference", sa.String(255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["processed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("refund_number"),
        sa.CheckConstraint("refund_amount > 0", name="ck_refund_amount_positive"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_refund_status"),
    )

    # 37. returns
    op.create_table(
        "returns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("return_number", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("refund_id", sa.BigInteger(), nullable=True),
        sa.Column("processed_by", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["refund_id"], ["refunds.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("return_number"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'cancelled')", name="ck_return_status"),
    )

    # 38. return_items
    op.create_table(
        "return_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("return_id", sa.BigInteger(), nullable=False),
        sa.Column("order_item_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("return_reason", sa.Text(), nullable=True),
        sa.Column("restock", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["return_id"], ["returns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("quantity > 0", name="ck_return_item_quantity_positive"),
    )

    # 39. coupon_usages
    op.create_table(
        "coupon_usages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("coupon_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
    )

    # =========================================================================
    # Domain: Configuration
    # =========================================================================

    # 40. system_settings
    op.create_table(
        "system_settings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(30), nullable=False, server_default="string"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "branch_id", "key", name="uq_system_setting_org_branch_key"),
    )

    # =========================================================================
    # Domain: Audit & Security
    # =========================================================================

    # 41. audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("before_data", postgresql.JSONB(), nullable=True),
        sa.Column("after_data", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_log_org_created", "audit_logs", ["organization_id", "created_at"])
    op.create_index("ix_audit_log_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_log_entity", "audit_logs", ["entity_type", "entity_id"])

    # 42. idempotency_keys
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(255), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", "endpoint", name="uq_idempotency_key_endpoint"),
    )
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("idempotency_keys")
    op.drop_table("audit_logs")
    op.drop_table("system_settings")
    op.drop_table("coupon_usages")
    op.drop_table("return_items")
    op.drop_table("returns")
    op.drop_table("refunds")
    op.drop_table("payments")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("coupons")
    op.drop_table("promotion_rules")
    op.drop_table("promotion_branches")
    op.drop_table("promotions")
    op.drop_table("shift_cash_movements")
    op.drop_table("shifts")
    op.drop_table("loyalty_transactions")
    op.drop_table("customers")
    op.drop_index("ix_inventory_lot_fefo", table_name="inventory_lots")
    op.drop_table("stock_transfer_items")
    op.drop_table("stock_transfers")
    op.drop_table("purchase_receiving_items")
    op.drop_table("purchase_receivings")
    op.drop_table("purchase_order_items")
    op.drop_table("purchase_orders")
    op.drop_table("stock_movements")
    op.drop_table("document_sequences")
    op.drop_table("inventory_lots")
    op.drop_table("inventory")
    op.drop_table("registers")
    op.drop_table("supplier_products")
    op.drop_table("suppliers")
    op.drop_table("products")
    op.drop_table("categories")
    op.drop_table("login_attempts")
    op.drop_table("refresh_tokens")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("branches")
    op.drop_table("organizations")

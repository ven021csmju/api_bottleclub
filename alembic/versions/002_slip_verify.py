"""Add slip verification tables - payment_verifications & verification_attempts

Revision ID: 002_slip_verify
Revises: 001_initial
Create Date: 2026-08-27 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_slip_verify"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. payment_verifications
    op.create_table(
        "payment_verifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),

        # Foreign keys
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True),

        # OCR extracted data
        sa.Column("ocr_raw_texts", postgresql.JSONB(), nullable=True),
        sa.Column("ocr_bank", sa.String(50), nullable=True),
        sa.Column("ocr_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("ocr_reference", sa.String(255), nullable=True),
        sa.Column("ocr_date", sa.Date(), nullable=True),
        sa.Column("ocr_time", sa.Time(), nullable=True),
        sa.Column("ocr_sender_name", sa.String(255), nullable=True),
        sa.Column("ocr_receiver_name", sa.String(255), nullable=True),
        sa.Column("ocr_sender_account", sa.String(50), nullable=True),
        sa.Column("ocr_receiver_account", sa.String(50), nullable=True),
        sa.Column("ocr_fee", sa.Numeric(12, 2), nullable=True),
        sa.Column("ocr_status_text", sa.String(100), nullable=True),
        sa.Column("ocr_field_confidences", postgresql.JSONB(), nullable=True),

        # Image metadata
        sa.Column("image_storage_key", sa.String(500), nullable=True),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("image_perceptual_hash", sa.String(64), nullable=True),
        sa.Column("image_mime_type", sa.String(50), nullable=True),
        sa.Column("image_file_size", sa.Integer(), nullable=True),

        # Verification result
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("risk_score", sa.Numeric(3, 2), nullable=False, server_default="0.00"),
        sa.Column("risk_signals", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),

        # Audit
        sa.Column("verified_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'review', 'amount_mismatch', "
            "'duplicate_reference', 'duplicate_image', 'order_not_found', 'order_already_paid', "
            "'ocr_failed', 'receiver_mismatch')",
            name="ck_verification_status",
        ),
    )

    # Unique on reference (excluding rejected) to prevent race conditions
    op.execute("""
        CREATE UNIQUE INDEX uq_verification_reference
        ON payment_verifications (ocr_reference)
        WHERE ocr_reference IS NOT NULL AND status != 'rejected'
    """)

    # Indexes
    op.create_index("ix_verification_order", "payment_verifications", ["order_id", "created_at"])
    op.create_index("ix_verification_image_hash", "payment_verifications", ["image_sha256"])
    op.create_index("ix_verification_status", "payment_verifications", ["status", "created_at"])
    op.create_index("ix_verification_created_by", "payment_verifications", ["created_by", "created_at"])

    # 2. verification_attempts
    op.create_table(
        "verification_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("verification_id", sa.BigInteger(), sa.ForeignKey("payment_verifications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),

        # Request info
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),

        # Input snapshot
        sa.Column("image_sha256", sa.String(64), nullable=True),
        sa.Column("ocr_reference", sa.String(255), nullable=True),
        sa.Column("ocr_amount", sa.Numeric(12, 2), nullable=True),

        # Result
        sa.Column("http_status", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("risk_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_attempts_user", "verification_attempts", ["user_id", "created_at"])
    op.create_index("ix_attempts_order", "verification_attempts", ["order_id", "created_at"])
    op.create_index("ix_attempts_created", "verification_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_table("verification_attempts")
    op.drop_index("ix_verification_created_by", "payment_verifications")
    op.drop_index("ix_verification_status", "payment_verifications")
    op.drop_index("ix_verification_image_hash", "payment_verifications")
    op.drop_index("ix_verification_order", "payment_verifications")
    op.execute("DROP INDEX IF EXISTS uq_verification_reference")
    op.drop_table("payment_verifications")

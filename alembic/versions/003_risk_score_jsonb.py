"""Alter risk_score from Numeric(3,2) to JSONB

Revision ID: 003_risk_score_jsonb
Revises: 002_slip_verify
Create Date: 2026-08-27 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_risk_score_jsonb"
down_revision: Union[str, None] = "002_slip_verify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # payment_verifications: NOT NULL + server_default
    op.alter_column(
        "payment_verifications",
        "risk_score",
        existing_type=sa.Numeric(3, 2),
        type_=postgresql.JSONB(),
        nullable=False,
        server_default="'{}'::jsonb",
        using="risk_score::jsonb",
    )

    # verification_attempts: nullable, no default
    op.alter_column(
        "verification_attempts",
        "risk_score",
        existing_type=sa.Numeric(3, 2),
        type_=postgresql.JSONB(),
        nullable=True,
        server_default=None,
        using="risk_score::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "verification_attempts",
        "risk_score",
        existing_type=postgresql.JSONB(),
        type_=sa.Numeric(3, 2),
        nullable=True,
        server_default=None,
        using="risk_score::numeric(3,2)",
    )

    op.alter_column(
        "payment_verifications",
        "risk_score",
        existing_type=postgresql.JSONB(),
        type_=sa.Numeric(3, 2),
        nullable=False,
        server_default="0.00",
        using="risk_score::numeric(3,2)",
    )

"""Phase 8: reports table.

Revision ID: 0004_reports
Revises: 0003_sentinel
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_reports"
down_revision = "0003_sentinel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("period", sa.String(8), nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("reports")

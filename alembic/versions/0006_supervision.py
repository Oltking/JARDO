"""Phase: supervision sessions (owner-declared oversight objective).

Revision ID: 0006_supervision
Revises: 0005_tasks
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_supervision"
down_revision = "0005_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supervision_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("owners.id"), nullable=False, index=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("supervision_sessions")

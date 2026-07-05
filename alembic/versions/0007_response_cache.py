"""Cost optimization: response cache.

Revision ID: 0007_response_cache
Revises: 0006_supervision
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_response_cache"
down_revision = "0006_supervision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "response_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cache_key", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("request_preview", sa.String(300), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("per_call_tokens", sa.Integer(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("response_cache")

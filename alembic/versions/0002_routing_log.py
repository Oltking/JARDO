"""Phase 2: routing_log for cost-router decisions.

Revision ID: 0002_routing_log
Revises: 0001_phase1_core
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_routing_log"
down_revision = "0001_phase1_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routing_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("task_id", sa.String(64), nullable=False, index=True),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("task_label", sa.String(16), nullable=False),
        sa.Column("est_cost_usd", sa.Float(), nullable=False),
        sa.Column("alternative_cost_usd", sa.Float(), nullable=False),
        sa.Column("saved_usd", sa.Float(), nullable=False),
        sa.Column("actual_cost_usd", sa.Float(), nullable=True),
        sa.Column("floor", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("routing_log")

"""Phase: tracked projects (owner's folders, for the resume-work "where am I?").

Revision ID: 0009_projects
Revises: 0008_semantic_cache
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_projects"
down_revision = "0008_semantic_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("owners.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=False,
                  index=True),
    )
    op.create_unique_constraint("uq_projects_owner_path", "projects",
                                ["owner_id", "path"])


def downgrade() -> None:
    op.drop_constraint("uq_projects_owner_path", "projects", type_="unique")
    op.drop_table("projects")

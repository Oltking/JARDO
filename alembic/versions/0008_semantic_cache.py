"""Semantic cache: pgvector embedding on the response cache.

Revision ID: 0008_semantic_cache
Revises: 0007_response_cache
Create Date: 2026-07-06
"""
from alembic import op

revision = "0008_semantic_cache"
down_revision = "0007_response_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector is available in the pgvector/pgvector image (infra/docker-compose.yml).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # nomic-embed-text produces 768-dim embeddings.
    op.execute("ALTER TABLE response_cache ADD COLUMN embedding vector(768)")


def downgrade() -> None:
    op.execute("ALTER TABLE response_cache DROP COLUMN IF EXISTS embedding")

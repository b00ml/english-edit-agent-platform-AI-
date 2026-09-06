"""add knowledge_chunk for RAG

Revision ID: a3f9c2e1d4b0
Revises: 19e15bc45345
Create Date: 2026-08-11 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector

# revision identifiers, used by Alembic.
revision: str = 'a3f9c2e1d4b0'
down_revision: Union[str, None] = '19e15bc45345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """启用 pgvector 扩展并创建知识分块表。"""
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table(
        'knowledge_chunk',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('source_type', sa.String(length=32), nullable=False),
        sa.Column('source_name', sa.String(length=128), nullable=False),
        sa.Column('knowledge_point', sa.String(length=128), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(dim=1024), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_knowledge_chunk_source_type', 'knowledge_chunk', ['source_type'])
    op.create_index('ix_knowledge_chunk_knowledge_point', 'knowledge_chunk', ['knowledge_point'])


def downgrade() -> None:
    """回滚：删除表与索引。"""
    op.drop_index('ix_knowledge_chunk_knowledge_point', table_name='knowledge_chunk')
    op.drop_index('ix_knowledge_chunk_source_type', table_name='knowledge_chunk')
    op.drop_table('knowledge_chunk')
    op.execute('DROP EXTENSION IF EXISTS vector')

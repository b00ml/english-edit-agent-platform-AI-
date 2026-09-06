"""add sample_pool table for high-quality sample pooling (data feedback)

Revision ID: f5a6b7c8d9e0
Revises: e4a1b2c3d5e6
Create Date: 2026-08-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'e4a1b2c3d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建高质量回流样本表 sample_pool。"""
    op.create_table(
        'sample_pool',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('item_id', sa.String(length=36), nullable=False),
        sa.Column('template_id', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False,
                  server_default='manual'),
        sa.Column('purpose', sa.String(length=32), nullable=False,
                  server_default='sft'),
        sa.Column('knowledge_point', sa.String(length=128), nullable=True),
        sa.Column('payload', sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column('meta', sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sample_pool_item_id', 'sample_pool', ['item_id'], unique=True)
    op.create_index('ix_sample_pool_template_id', 'sample_pool', ['template_id'])
    op.create_index('ix_sample_pool_knowledge_point', 'sample_pool', ['knowledge_point'])


def downgrade() -> None:
    """回滚：删除索引与表。"""
    op.drop_index('ix_sample_pool_knowledge_point', table_name='sample_pool')
    op.drop_index('ix_sample_pool_template_id', table_name='sample_pool')
    op.drop_index('ix_sample_pool_item_id', table_name='sample_pool')
    op.drop_table('sample_pool')

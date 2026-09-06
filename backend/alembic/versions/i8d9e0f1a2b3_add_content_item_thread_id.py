"""add thread_id to content_item for human review resume

Revision ID: i8d9e0f1a2b3
Revises: h7c8d9e0f1a2
Create Date: 2026-09-05 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'i8d9e0f1a2b3'
down_revision: Union[str, None] = 'h7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """content_item 增加 LangGraph 线程 ID（灰区人工卡点恢复凭据，P1-1）。"""
    op.add_column(
        'content_item',
        sa.Column('thread_id', sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除字段。"""
    op.drop_column('content_item', 'thread_id')

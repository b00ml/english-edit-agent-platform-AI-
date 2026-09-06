"""add request_hash to generation_task for dedup

Revision ID: b7c4d9e2f1a0
Revises: a3f9c2e1d4b0
Create Date: 2026-08-11 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7c4d9e2f1a0'
down_revision: Union[str, None] = 'a3f9c2e1d4b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 generation_task 增加去重指纹列并建索引。"""
    op.add_column(
        'generation_task',
        sa.Column('request_hash', sa.String(length=64), nullable=True),
    )
    op.create_index(
        'ix_generation_task_request_hash', 'generation_task', ['request_hash']
    )


def downgrade() -> None:
    """回滚：删除索引与列。"""
    op.drop_index('ix_generation_task_request_hash', table_name='generation_task')
    op.drop_column('generation_task', 'request_hash')
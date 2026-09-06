"""add task_id to trace_log for per-task cost aggregation

Revision ID: c2d8e4f6a1b3
Revises: b7c4d9e2f1a0
Create Date: 2026-08-11 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c2d8e4f6a1b3'
down_revision: Union[str, None] = 'b7c4d9e2f1a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 trace_log 增加 task_id 列并建索引。"""
    op.add_column(
        'trace_log',
        sa.Column('task_id', sa.String(length=36), nullable=True),
    )
    op.create_index('ix_trace_log_task_id', 'trace_log', ['task_id'])


def downgrade() -> None:
    """回滚：删除索引与列。"""
    op.drop_index('ix_trace_log_task_id', table_name='trace_log')
    op.drop_column('trace_log', 'task_id')
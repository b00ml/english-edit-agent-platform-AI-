"""add attempt and success to trace_log for structured conformity stats

Revision ID: h7c8d9e0f1a2
Revises: g6b7c8d9e0f1
Create Date: 2026-09-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'h7c8d9e0f1a2'
down_revision: Union[str, None] = 'g6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 trace_log 增加尝试序号与校验结果字段（结构化符合率埋点）。

    历史行按 attempt=1 / success=true 解释（默认值），与新指标口径平滑兼容。
    """
    op.add_column(
        'trace_log',
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
    )
    op.add_column(
        'trace_log',
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    )


def downgrade() -> None:
    """回滚：删除两个字段。"""
    op.drop_column('trace_log', 'success')
    op.drop_column('trace_log', 'attempt')

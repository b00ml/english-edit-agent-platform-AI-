"""add token breakdown and stage to trace_log for deep cost report

Revision ID: a7b8c9d0e1f2
Revises: f5a6b7c8d9e0
Create Date: 2026-08-13 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 trace_log 增加调用阶段与 token 细分字段。"""
    op.add_column('trace_log', sa.Column('stage', sa.String(length=32), nullable=True))
    op.add_column('trace_log', sa.Column('prompt_tokens', sa.Integer(), nullable=True))
    op.add_column('trace_log', sa.Column('completion_tokens', sa.Integer(), nullable=True))
    op.create_index('ix_trace_log_stage', 'trace_log', ['stage'])


def downgrade() -> None:
    """回滚：删除索引与字段。"""
    op.drop_index('ix_trace_log_stage', table_name='trace_log')
    op.drop_column('trace_log', 'completion_tokens')
    op.drop_column('trace_log', 'prompt_tokens')
    op.drop_column('trace_log', 'stage')

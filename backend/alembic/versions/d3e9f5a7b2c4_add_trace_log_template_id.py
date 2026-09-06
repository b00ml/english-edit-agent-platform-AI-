"""add template_id to trace_log for per-template cost aggregation

Revision ID: d3e9f5a7b2c4
Revises: c2d8e4f6a1b3
Create Date: 2026-08-11 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd3e9f5a7b2c4'
down_revision: Union[str, None] = 'c2d8e4f6a1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 trace_log 增加 template_id 列并建索引。"""
    op.add_column(
        'trace_log',
        sa.Column('template_id', sa.String(length=64), nullable=True),
    )
    op.create_index('ix_trace_log_template_id', 'trace_log', ['template_id'])


def downgrade() -> None:
    """回滚：删除索引与列。"""
    op.drop_index('ix_trace_log_template_id', table_name='trace_log')
    op.drop_column('trace_log', 'template_id')
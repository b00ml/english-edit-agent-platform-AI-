"""add quality_calibration table + quality_record.reason column (J1 quality calibration)

Revision ID: g6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-08-13 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'g6b7c8d9e0f1'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建质检校准记录表 + 为 quality_record 增加 reason 列。"""
    # 1) 新增 quality_calibration 表
    op.create_table(
        'quality_calibration',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('template_id', sa.String(length=64), nullable=False),
        sa.Column('weights', sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('default_weights', sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column('default_threshold', sa.Float(), nullable=False),
        sa.Column('sample_size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('false_pass_cnt', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lenient', sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column('rejection_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('tenant_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_quality_calibration_template_id', 'quality_calibration', ['template_id'])

    # 2) 为 quality_record 增加 reason 列（人工驳回原因）
    op.add_column('quality_record',
                  sa.Column('reason', sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚：删除 reason 列与 quality_calibration 表。"""
    op.drop_column('quality_record', 'reason')
    op.drop_index('ix_quality_calibration_template_id', table_name='quality_calibration')
    op.drop_table('quality_calibration')

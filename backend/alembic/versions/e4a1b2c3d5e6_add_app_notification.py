"""add app_notification table for in-app notifications

Revision ID: e4a1b2c3d5e6
Revises: d3e9f5a7b2c4
Create Date: 2026-08-12 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e4a1b2c3d5e6'
down_revision: Union[str, None] = 'd3e9f5a7b2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建站内消息表 app_notification。"""
    op.create_table(
        'app_notification',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=128), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('related_id', sa.String(length=36), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('tenant_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_app_notification_related_id', 'app_notification', ['related_id'])


def downgrade() -> None:
    """回滚：删除索引与表。"""
    op.drop_index('ix_app_notification_related_id', table_name='app_notification')
    op.drop_table('app_notification')
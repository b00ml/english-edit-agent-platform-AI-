"""add cancel_requested_at to generation_task

Revision ID: 260907181909_add_cancel
Revises: 19e15bc45345
Create Date: 2026-09-07 18:19:09

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "260907181909_add_cancel"
down_revision: Union[str, None] = "19e15bc45345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加任务取消时间戳字段。"""
    op.add_column(
        "generation_task",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除取消时间戳字段。"""
    op.drop_column("generation_task", "cancel_requested_at")

"""批次 A P0 可靠性和权限改造

Revision ID: m3_01_batch_a_p0
Revises: i8d9e0f1a2b3
Create Date: 2026-09-08 14:30:00.000000

新增表：
- generation_task_item: 单个子任务条目，记录 thread_id/status/failure_code/attempts

新增字段：
- generation_task.result_summary: JSONB，任务整体结果摘要
- content_item.failure_code, failure_reason, published_by, published_at: 失败码、失败原因、发布人、发布时间
- app_notification.event_id: 事件幂等键（唯一约束）

约束：
- generation_task_item: (task_id, item_index) 唯一索引
- generation_task_item.thread_id 唯一索引
- app_notification.event_id 唯一约束
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "m3_01_batch_a_p0"
down_revision = "i8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    # 1. 新增 generation_task_item 表
    op.create_table(
        "generation_task_item",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("generation_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_index", sa.Integer, nullable=False),
        sa.Column("thread_id", sa.String(128), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "content_id",
            sa.String(36),
            sa.ForeignKey("content_item.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_generation_task_item_task_id", "generation_task_item", ["task_id"])
    op.create_index("ix_generation_task_item_tenant_id", "generation_task_item", ["tenant_id"])
    op.create_unique_constraint(
        "uq_generation_task_item_index", "generation_task_item", ["task_id", "item_index"]
    )

    # 2. generation_task 新增 result_summary 字段
    op.add_column("generation_task", sa.Column("result_summary", postgresql.JSONB, nullable=True))

    # 3. content_item 新增 4 个字段
    op.add_column("content_item", sa.Column("failure_code", sa.String(64), nullable=True))
    op.add_column("content_item", sa.Column("failure_reason", sa.Text, nullable=True))
    op.add_column("content_item", sa.Column("published_by", sa.String(36), nullable=True))
    op.add_column(
        "content_item", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )

    # 4. app_notification 新增 event_id 字段（唯一约束）
    op.add_column("app_notification", sa.Column("event_id", sa.String(128), nullable=True))
    op.create_unique_constraint("uq_app_notification_event_id", "app_notification", ["event_id"])


def downgrade():
    # 反向迁移：删除约束和字段
    op.drop_constraint("uq_app_notification_event_id", "app_notification", type_="unique")
    op.drop_column("app_notification", "event_id")

    op.drop_column("content_item", "published_at")
    op.drop_column("content_item", "published_by")
    op.drop_column("content_item", "failure_reason")
    op.drop_column("content_item", "failure_code")

    op.drop_column("generation_task", "result_summary")

    op.drop_constraint("uq_generation_task_item_index", "generation_task_item", type_="unique")
    op.drop_index("ix_generation_task_item_tenant_id", "generation_task_item")
    op.drop_index("ix_generation_task_item_task_id", "generation_task_item")
    op.drop_table("generation_task_item")

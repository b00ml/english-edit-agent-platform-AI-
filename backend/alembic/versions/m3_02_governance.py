"""Add runtime governance snapshots, model health and task outbox.

Revision ID: m3_02_governance
Revises: m3_merge_cancel_batch_a
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "m3_02_governance"
down_revision: Union[str, None] = "m3_merge_cancel_batch_a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("question_template", sa.Column("template_hash", sa.String(64), nullable=True))
    op.add_column("question_template", sa.Column("prompt_hash", sa.String(64), nullable=True))
    op.add_column("question_template", sa.Column("skill_hash", sa.String(64), nullable=True))
    op.create_index("ix_question_template_template_hash", "question_template", ["template_hash"])
    op.create_index("ix_question_template_prompt_hash", "question_template", ["prompt_hash"])
    op.create_index("ix_question_template_skill_hash", "question_template", ["skill_hash"])

    op.add_column(
        "generation_task",
        sa.Column("version_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("quality_record", sa.Column("template_version", sa.Integer(), nullable=True))
    op.add_column(
        "quality_record",
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.add_column(
        "model_profile",
        sa.Column("status", sa.String(24), nullable=False, server_default="enabled"),
    )
    op.add_column(
        "model_profile",
        sa.Column("health_status", sa.String(24), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "model_profile",
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "model_profile", sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "model_profile",
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "model_profile",
        sa.Column("max_fallbacks", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("model_profile", sa.Column("budget_per_task", sa.Float(), nullable=True))

    op.create_table(
        "task_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("generation_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("event_id", name="uq_task_outbox_event_id"),
    )
    op.create_index("ix_task_outbox_task_id", "task_outbox", ["task_id"])
    op.create_index("ix_task_outbox_item_id", "task_outbox", ["item_id"])
    op.create_index("ix_task_outbox_status", "task_outbox", ["status"])
    op.create_index("ix_task_outbox_available_at", "task_outbox", ["available_at"])
    op.create_index("ix_task_outbox_tenant_id", "task_outbox", ["tenant_id"])

    op.create_table(
        "config_audit_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("tenant_id", sa.String(64), nullable=True),
        sa.Column("before_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_config_audit_event_entity_type", "config_audit_event", ["entity_type"])
    op.create_index("ix_config_audit_event_entity_id", "config_audit_event", ["entity_id"])
    op.create_index("ix_config_audit_event_tenant_id", "config_audit_event", ["tenant_id"])
    op.create_index("ix_config_audit_event_created_at", "config_audit_event", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_config_audit_event_created_at", table_name="config_audit_event")
    op.drop_index("ix_config_audit_event_tenant_id", table_name="config_audit_event")
    op.drop_index("ix_config_audit_event_entity_id", table_name="config_audit_event")
    op.drop_index("ix_config_audit_event_entity_type", table_name="config_audit_event")
    op.drop_table("config_audit_event")

    op.drop_index("ix_task_outbox_tenant_id", table_name="task_outbox")
    op.drop_index("ix_task_outbox_available_at", table_name="task_outbox")
    op.drop_index("ix_task_outbox_status", table_name="task_outbox")
    op.drop_index("ix_task_outbox_item_id", table_name="task_outbox")
    op.drop_index("ix_task_outbox_task_id", table_name="task_outbox")
    op.drop_table("task_outbox")

    op.drop_column("model_profile", "budget_per_task")
    op.drop_column("model_profile", "max_fallbacks")
    op.drop_column("model_profile", "last_health_check_at")
    op.drop_column("model_profile", "cooldown_until")
    op.drop_column("model_profile", "failure_count")
    op.drop_column("model_profile", "health_status")
    op.drop_column("model_profile", "status")
    op.drop_column("quality_record", "config_snapshot")
    op.drop_column("quality_record", "template_version")
    op.drop_column("generation_task", "version_snapshot")
    op.drop_index("ix_question_template_skill_hash", table_name="question_template")
    op.drop_index("ix_question_template_prompt_hash", table_name="question_template")
    op.drop_index("ix_question_template_template_hash", table_name="question_template")
    op.drop_column("question_template", "skill_hash")
    op.drop_column("question_template", "prompt_hash")
    op.drop_column("question_template", "template_hash")

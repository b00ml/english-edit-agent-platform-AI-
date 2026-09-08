"""Add model profile content hash for immutable task governance."""

import sqlalchemy as sa

from alembic import op

revision = "m3_03_model_hash"
down_revision = "m3_02_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_profile", sa.Column("model_hash", sa.String(64), nullable=True))
    op.create_index("ix_model_profile_model_hash", "model_profile", ["model_hash"])


def downgrade() -> None:
    op.drop_index("ix_model_profile_model_hash", table_name="model_profile")
    op.drop_column("model_profile", "model_hash")

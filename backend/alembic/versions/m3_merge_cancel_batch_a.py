"""Merge the cancel-request and batch-A migration branches.

Revision ID: m3_merge_cancel_batch_a
Revises: 260907181909_add_cancel, m3_01_batch_a_p0
"""

from typing import Sequence, Union

revision: str = "m3_merge_cancel_batch_a"
down_revision: Union[str, tuple[str, str], None] = (
    "260907181909_add_cancel",
    "m3_01_batch_a_p0",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge revision; both parent branches are retained."""


def downgrade() -> None:
    """No-op merge revision; parent revisions own their downgrade operations."""

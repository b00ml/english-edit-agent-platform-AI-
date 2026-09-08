# app/domain/status.py —— 状态契约（优化技术设计 3.0 / P0-1）
# 集中定义任务、任务条目与内容状态，禁止在 API / workflow / worker 中散落魔法值。
from typing import Final

# ---------------------------------------------------------------------------
# 生成任务
# ---------------------------------------------------------------------------
TASK_PENDING: Final = "pending"
TASK_DISPATCHED: Final = "dispatched"
TASK_RUNNING: Final = "running"
TASK_AWAITING_REVIEW: Final = "awaiting_review"
TASK_SUCCEEDED: Final = "succeeded"
TASK_PARTIALLY_SUCCEEDED: Final = "partially_succeeded"
TASK_FAILED: Final = "failed"
TASK_CANCELLED: Final = "cancelled"

ACTIVE_TASK_STATUSES: Final[tuple[str, ...]] = (
    TASK_PENDING,
    TASK_DISPATCHED,
    TASK_RUNNING,
    TASK_AWAITING_REVIEW,
)

TERMINAL_TASK_STATUSES: Final[tuple[str, ...]] = (
    TASK_SUCCEEDED,
    TASK_PARTIALLY_SUCCEEDED,
    TASK_FAILED,
    TASK_CANCELLED,
)

# ---------------------------------------------------------------------------
# 生成任务条目（generation_task_item）
# ---------------------------------------------------------------------------
ITEM_QUEUED: Final = "queued"
ITEM_RUNNING: Final = "running"
ITEM_STORED: Final = "stored"
ITEM_AWAITING_REVIEW: Final = "awaiting_review"
ITEM_REJECTED: Final = "rejected"
ITEM_FAILED: Final = "failed"
ITEM_CANCELLED: Final = "cancelled"

TERMINAL_ITEM_STATUSES: Final[tuple[str, ...]] = (
    ITEM_STORED,
    ITEM_AWAITING_REVIEW,
    ITEM_REJECTED,
    ITEM_FAILED,
    ITEM_CANCELLED,
)

# ---------------------------------------------------------------------------
# 内容条目
# ---------------------------------------------------------------------------
CONTENT_PENDING_QC: Final = "pending_qc"
CONTENT_PASSED: Final = "passed"
CONTENT_REJECTED: Final = "rejected"
CONTENT_PUBLISHED: Final = "published"
CONTENT_AWAITING_REVIEW: Final = "awaiting_review"

CONTENT_TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {
    CONTENT_PENDING_QC: (CONTENT_PASSED, CONTENT_REJECTED, CONTENT_AWAITING_REVIEW),
    CONTENT_AWAITING_REVIEW: (CONTENT_PASSED, CONTENT_REJECTED),
    CONTENT_PASSED: (CONTENT_PUBLISHED,),
    CONTENT_PUBLISHED: (),
    CONTENT_REJECTED: (),
}


def can_transition_content(current: str, target: str) -> bool:
    """判断内容状态是否允许从 current 迁移到 target。"""
    return target in CONTENT_TRANSITIONS.get(current, ())

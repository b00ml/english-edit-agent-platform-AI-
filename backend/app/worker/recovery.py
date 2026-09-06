# app/worker/recovery.py —— 僵尸任务恢复（P0-6 / OPT-019）
# worker 崩溃/断电后任务可能永久卡在 running。worker 启动时（celery worker_ready 信号）
# 将「running 且 updated_at 超过 STALE_TASK_SECONDS」的任务重置为 pending 并重新入队；
# 配合 PostgresSaver 的 thread 级检查点，重跑只续跑未完成条目，已完成条目幂等跳过。
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import GenerationTask

logger = logging.getLogger("app.worker.recovery")


def _select_stale(session: Session, cutoff: datetime) -> List[GenerationTask]:
    """查询僵尸任务：running 且 updated_at 早于 cutoff。"""
    return (
        session.query(GenerationTask)
        .filter(GenerationTask.status == "running")
        .filter(GenerationTask.updated_at < cutoff)
        .all()
    )


def recover_stale_tasks(
    session: Session,
    now: Optional[datetime] = None,
    enqueue: Optional[Callable[[str], None]] = None,
) -> int:
    """恢复僵尸任务：置回 pending 并重新入队，返回恢复数量。

    enqueue 参数注入任务投递函数（默认 process_generation_task.delay），
    便于单测替换。updated_at 由 onupdate 在提交时自动刷新，重置后即脱离僵尸判定窗口。
    """
    if enqueue is None:
        from app.worker.tasks import process_generation_task

        enqueue = process_generation_task.delay

    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.STALE_TASK_SECONDS)

    stale = _select_stale(session, cutoff)
    for task in stale:
        task.status = "pending"
        session.commit()
        enqueue(task.id)
        logger.warning("僵尸任务已恢复: task_id=%s（running 超时 -> pending 重新入队）", task.id)
    return len(stale)

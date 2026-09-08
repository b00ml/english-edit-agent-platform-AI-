"""任务 Outbox 事务写入、relay 与死信重放。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.models import GenerationTask, TaskOutbox

logger = logging.getLogger("app.outbox")

OutboxSender = Callable[..., Any]


def create_generation_dispatch(session: Session, task: GenerationTask) -> TaskOutbox:
    """在生成任务同一事务中写入稳定 event_id 的 dispatch 事件。"""
    event_id = f"task:{task.id}:dispatch"
    existing = session.query(TaskOutbox).filter(TaskOutbox.event_id == event_id).first()
    if existing is not None:
        return existing
    event = TaskOutbox(
        event_id=event_id,
        task_id=task.id,
        event_type="generation_dispatch",
        payload={"task_id": task.id},
        status="pending",
        tenant_id=task.tenant_id,
    )
    session.add(event)
    return event


def _send_event(event: TaskOutbox, sender: OutboxSender) -> None:
    """使用稳定 Celery task_id 投递单个事件。"""
    task_id = str(event.payload["task_id"])
    sender(
        # 保留旧入口名，兼容已部署 worker；该任务内部再拆分 item。
        "app.worker.tasks.process_generation_task",
        [task_id],
        task_id=event.event_id,
    )


def relay_pending(
    session: Session,
    sender: OutboxSender,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    """领取并投递 pending 事件，失败按次数进入 dead。"""
    batch_size = limit or settings.OUTBOX_RELAY_BATCH_SIZE
    now = datetime.now(timezone.utc)
    # 进程在 send_task 后崩溃时会留下 sending 事件。Celery 投递使用稳定
    # event_id，因此回收后重复投递仍由下游任务/checkpoint 保持幂等。
    stale_before = now - timedelta(seconds=settings.OUTBOX_SENDING_TIMEOUT_SECONDS)
    session.query(TaskOutbox).filter(
        TaskOutbox.status == "sending",
        TaskOutbox.updated_at <= stale_before,
    ).update(
        {
            TaskOutbox.status: "pending",
            TaskOutbox.available_at: now,
        },
        synchronize_session=False,
    )
    session.commit()
    events = (
        session.query(TaskOutbox)
        .filter(TaskOutbox.status == "pending")
        .filter(TaskOutbox.available_at <= now)
        .order_by(TaskOutbox.created_at.asc())
        .limit(batch_size)
        .all()
    )
    sent = 0
    dead = 0
    for event in events:
        event.status = "sending"
        event.attempts += 1
        session.commit()
        try:
            _send_event(event, sender)
        except Exception as exc:  # noqa: BLE001 - relay must persist failure for retry/dead-letter
            event.last_error = str(exc)[:1000]
            if event.attempts >= settings.OUTBOX_MAX_ATTEMPTS:
                event.status = "dead"
                dead += 1
            else:
                event.status = "pending"
                event.available_at = now + timedelta(
                    seconds=settings.OUTBOX_RETRY_BACKOFF_SECONDS * (2 ** (event.attempts - 1))
                )
            session.commit()
            logger.warning(
                "outbox relay failed event_id=%s attempt=%s status=%s",
                event.event_id,
                event.attempts,
                event.status,
                exc_info=True,
            )
            continue
        event.status = "sent"
        event.sent_at = datetime.now(timezone.utc)
        event.last_error = None
        session.commit()
        sent += 1
    return {"sent": sent, "dead": dead, "scanned": len(events)}


def replay_dead(session: Session, event_id: str) -> TaskOutbox:
    """将指定死信恢复为 pending；不删除历史错误和尝试次数。"""
    event = session.query(TaskOutbox).filter(TaskOutbox.id == event_id).first()
    if event is None:
        raise ValueError(f"outbox event not found: {event_id}")
    if event.status != "dead":
        raise ValueError(f"outbox event is not dead: {event.status}")
    event.status = "pending"
    event.available_at = datetime.now(timezone.utc)
    session.commit()
    return event

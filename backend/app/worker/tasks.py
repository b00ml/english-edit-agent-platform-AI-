# app/worker/tasks.py —— Celery 批量生成任务（P1-3 重构：取消 + 并发）
from datetime import datetime, timezone

from celery import shared_task
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import SessionLocal
from app.engine.trace import record_lifecycle_event
from app.models import GenerationTask, GenerationTaskItem
from app.notification import notify_task_result
from app.outbox import relay_pending
from app.workflow.graph import run_generation

# 任务状态常量
PENDING = "pending"
DISPATCHED = "dispatched"
RUNNING = "running"
PARTIALLY_SUCCEEDED = "partially_succeeded"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"


@shared_task(
    name="app.worker.tasks.relay_task_outbox",
    bind=True,
    max_retries=settings.TASK_MAX_RETRIES,
    autoretry_for=(RedisConnectionError, RedisTimeoutError, OperationalError),
    retry_backoff=True,
    acks_late=True,
)
def relay_task_outbox(self) -> dict:
    """投递数据库 Outbox；发送失败按 attempts 进入 dead，供管理员重放。"""
    from app.worker.celery_app import celery_app

    session = SessionLocal()
    try:
        result = relay_pending(
            session,
            lambda name, args, task_id=None: celery_app.send_task(name, args=args, task_id=task_id),
        )
        return result
    finally:
        session.close()


@shared_task(
    name="app.worker.tasks.dispatch_generation_items",
    bind=True,
    max_retries=settings.TASK_MAX_RETRIES,
    autoretry_for=(RedisConnectionError, RedisTimeoutError, OperationalError),
    retry_backoff=True,
    default_retry_delay=60,
    acks_late=True,
)
def dispatch_generation_items(self, task_id: str) -> dict:
    """调度器：将批量任务拆分为独立 item，投递到 Celery 队列。

    职责：
    1. 检查任务是否已取消
    2. 为每个 item 创建 GenerationTaskItem 记录
    3. 投递 N 个独立的 generate_single_item 任务
    4. 更新父任务状态为 dispatched
    """
    trace_id = f"task:{task_id}"
    started = datetime.now(timezone.utc)
    record_lifecycle_event(
        trace_id=trace_id,
        stage="queue_dispatch",
        event="started",
        model="celery",
        task_id=task_id,
    )
    session = SessionLocal()
    try:
        task = session.query(GenerationTask).filter(GenerationTask.id == task_id).first()
        if task is None:
            record_lifecycle_event(
                trace_id=trace_id,
                stage="queue_dispatch",
                event="failed",
                model="celery",
                task_id=task_id,
                status=FAILED,
                reason="任务不存在",
                success=False,
            )
            return {"task_id": task_id, "status": FAILED, "reason": "任务不存在"}

        trace_id = task.trace_ref or trace_id
        task.trace_ref = trace_id

        # 检查是否已取消
        if task.cancel_requested_at:
            task.status = CANCELLED
            session.commit()
            record_lifecycle_event(
                trace_id=trace_id,
                stage="queue_dispatch",
                event="finished",
                model="celery",
                task_id=task_id,
                status=CANCELLED,
                reason="任务已在调度前取消",
                success=False,
            )
            return {"task_id": task_id, "status": CANCELLED, "reason": "任务已在调度前取消"}

        quantity = task.quantity
        tenant_id = task.tenant_id or "default"

        # 创建 N 个 GenerationTaskItem 记录
        for idx in range(quantity):
            existing = (
                session.query(GenerationTaskItem)
                .filter(GenerationTaskItem.task_id == task_id, GenerationTaskItem.item_index == idx)
                .first()
            )
            if existing is not None:
                continue
            thread_id = f"{task_id}:{idx}"
            item = GenerationTaskItem(
                task_id=task_id,
                item_index=idx,
                thread_id=thread_id,
                status=PENDING,
                tenant_id=tenant_id,
            )
            session.add(item)

        # 更新父任务状态为 dispatched
        task.status = DISPATCHED
        session.commit()

        # 投递 N 个独立任务到 Celery 队列
        for idx in range(quantity):
            generate_single_item.delay(task_id, idx)

        record_lifecycle_event(
            trace_id=trace_id,
            stage="queue_dispatch",
            event="finished",
            model="celery",
            task_id=task_id,
            status=DISPATCHED,
            latency_ms=(datetime.now(timezone.utc) - started).total_seconds() * 1000,
            metadata={"item_count": quantity},
        )
        return {
            "task_id": task_id,
            "status": DISPATCHED,
            "total": quantity,
            "message": f"{quantity} 个 item 已投递到队列",
        }
    except Exception as exc:  # noqa: BLE001 - record queue failure then preserve retry semantics
        record_lifecycle_event(
            trace_id=trace_id,
            stage="queue_dispatch",
            event="failed",
            model="celery",
            task_id=task_id,
            status=FAILED,
            reason=str(exc),
            success=False,
            latency_ms=(datetime.now(timezone.utc) - started).total_seconds() * 1000,
        )
        raise
    finally:
        session.close()


@shared_task(
    name="app.worker.tasks.process_generation_task",
    bind=True,
    max_retries=settings.TASK_MAX_RETRIES,
    autoretry_for=(RedisConnectionError, RedisTimeoutError, OperationalError),
    retry_backoff=True,
    default_retry_delay=60,
    acks_late=True,
)
def process_generation_task(self, task_id: str) -> dict:
    """兼容旧任务名，将旧批量入口转发到 item 调度器。"""
    return dispatch_generation_items.run(task_id)


@shared_task(
    name="app.worker.tasks.generate_single_item",
    bind=True,
    max_retries=3,
    autoretry_for=(RedisConnectionError, RedisTimeoutError, OperationalError),
    retry_backoff=True,
    default_retry_delay=60,
    acks_late=True,
)
def generate_single_item(self, task_id: str, item_index: int) -> dict:
    """单 item worker：检查取消 → 执行生成 → 更新状态。

    幂等性：通过 GenerationTaskItem.thread_id 唯一约束 + PostgresSaver checkpoint 保证。
    失败分类：
    - 422/400：永久性失败，不重试
    - 429/503/500：临时性失败，指数退避重试
    - 基础设施错误（Redis/DB）：自动重试（autoretry_for）
    """
    trace_id = f"{task_id}:{item_index}"
    session = SessionLocal()
    try:
        task = session.query(GenerationTask).filter(GenerationTask.id == task_id).first()
        if task is None:
            record_lifecycle_event(
                trace_id=trace_id,
                stage="queue_item",
                event="failed",
                model="celery",
                task_id=task_id,
                item_id=trace_id,
                status=FAILED,
                reason="父任务不存在",
                success=False,
            )
            return {
                "task_id": task_id,
                "item_index": item_index,
                "status": FAILED,
                "reason": "父任务不存在",
            }

        # 检查父任务是否已取消
        if task.cancel_requested_at:
            # 更新 item 状态为 cancelled（如果记录存在）
            item = (
                session.query(GenerationTaskItem)
                .filter(
                    GenerationTaskItem.task_id == task_id,
                    GenerationTaskItem.item_index == item_index,
                )
                .first()
            )
            if item:
                item.status = CANCELLED
                session.commit()
            record_lifecycle_event(
                trace_id=trace_id,
                stage="queue_item",
                event="finished",
                model="celery",
                task_id=task_id,
                item_id=item.id if item else None,
                status=CANCELLED,
                reason="父任务已取消",
                success=False,
            )
            return {
                "task_id": task_id,
                "item_index": item_index,
                "status": CANCELLED,
                "reason": "父任务已取消",
            }

        # 获取或创建 GenerationTaskItem 记录
        thread_id = f"{task_id}:{item_index}"
        item = (
            session.query(GenerationTaskItem)
            .filter(
                GenerationTaskItem.task_id == task_id,
                GenerationTaskItem.item_index == item_index,
            )
            .first()
        )

        if not item:
            # 兜底创建（理论上 dispatch 阶段已创建）
            item = GenerationTaskItem(
                task_id=task_id,
                item_index=item_index,
                thread_id=thread_id,
                status=PENDING,
                tenant_id=task.tenant_id or "default",
            )
            session.add(item)
            session.commit()

        # 检查 item 是否已完成（幂等性保护）
        if item.status in [SUCCEEDED, "awaiting_review", FAILED, CANCELLED]:
            record_lifecycle_event(
                trace_id=item.thread_id,
                stage="queue_item",
                event="skipped",
                model="celery",
                task_id=task_id,
                item_id=item.id,
                status=item.status,
                reason="item 已完成，跳过重复执行",
            )
            return {
                "task_id": task_id,
                "item_index": item_index,
                "status": item.status,
                "reason": "item 已完成，跳过重复执行",
            }

        # 更新 item 状态为 running
        item.status = RUNNING
        item.started_at = datetime.now(timezone.utc)
        item.attempts += 1
        session.commit()
        item_started = datetime.now(timezone.utc)
        record_lifecycle_event(
            trace_id=item.thread_id,
            stage="queue_item",
            event="started",
            model="celery",
            task_id=task_id,
            item_id=item.id,
            template_id=task.template_id,
            tenant_id=item.tenant_id,
            metadata={"item_index": item_index, "attempt": item.attempts},
        )

        # 调用 workflow 生成
        try:
            result = run_generation(
                task_id=task_id,
                template_id=task.template_id,
                params=task.params,
                session=session,
                thread_id=thread_id,
            )
            final_status = result.get("status")

            # 更新 item 状态
            if final_status == "stored":
                item.status = SUCCEEDED
                item.content_id = result.get("content_id")
            elif final_status == "awaiting_review":
                item.status = "awaiting_review"
                item.content_id = result.get("content_id")
            elif final_status == "rejected":
                item.status = FAILED
                item.failure_code = result.get("failure_code", "QUALITY_REJECTED")
                item.failure_reason = result.get("reason", "质检未通过")
            elif final_status == CANCELLED:
                item.status = CANCELLED
                item.failure_reason = result.get("reason", "任务已取消")
            elif result.get("__interrupt__"):
                # 灰区人工卡点
                item.status = "awaiting_review"
                item.content_id = result.get("content_id")
            else:
                item.status = SUCCEEDED
                item.content_id = result.get("content_id")

            item.finished_at = datetime.now(timezone.utc)
            session.commit()

        except Exception as exc:  # noqa: BLE001
            # 失败分类
            error_msg = str(exc)

            # 永久性失败（422/400）：不重试
            if "422" in error_msg or "400" in error_msg or "Unprocessable Entity" in error_msg:
                item.status = FAILED
                item.failure_code = "PERMANENT_ERROR"
                item.failure_reason = error_msg
                item.finished_at = datetime.now(timezone.utc)
                session.commit()
                record_lifecycle_event(
                    trace_id=item.thread_id,
                    stage="queue_item",
                    event="failed",
                    model="celery",
                    task_id=task_id,
                    item_id=item.id,
                    template_id=task.template_id,
                    tenant_id=item.tenant_id,
                    status=FAILED,
                    reason=error_msg,
                    success=False,
                    latency_ms=(datetime.now(timezone.utc) - item_started).total_seconds() * 1000,
                )
                return {
                    "task_id": task_id,
                    "item_index": item_index,
                    "status": FAILED,
                    "failure_code": "PERMANENT_ERROR",
                    "reason": error_msg,
                }

            # 临时性失败（429/503/500）：指数退避重试
            if "429" in error_msg or "503" in error_msg or "500" in error_msg:
                item.failure_code = "TRANSIENT_ERROR"
                item.failure_reason = error_msg
                session.commit()
                record_lifecycle_event(
                    trace_id=item.thread_id,
                    stage="queue_item",
                    event="retry_scheduled",
                    model="celery",
                    task_id=task_id,
                    item_id=item.id,
                    template_id=task.template_id,
                    tenant_id=item.tenant_id,
                    status="retrying",
                    reason=error_msg,
                    success=False,
                    latency_ms=(datetime.now(timezone.utc) - item_started).total_seconds() * 1000,
                    metadata={"countdown_seconds": 2**item.attempts},
                )
                # 指数退避：2^attempts 秒
                countdown = 2**item.attempts
                raise self.retry(countdown=countdown, exc=exc)

            # 其他异常：标准重试
            item.failure_code = "UNKNOWN_ERROR"
            item.failure_reason = error_msg
            session.commit()
            record_lifecycle_event(
                trace_id=item.thread_id,
                stage="queue_item",
                event="failed",
                model="celery",
                task_id=task_id,
                item_id=item.id,
                template_id=task.template_id,
                tenant_id=item.tenant_id,
                status=FAILED,
                reason=error_msg,
                success=False,
                latency_ms=(datetime.now(timezone.utc) - item_started).total_seconds() * 1000,
            )
            raise

        # 原子性更新父任务进度
        _update_parent_task_progress(session, task_id)

        record_lifecycle_event(
            trace_id=item.thread_id,
            stage="queue_item",
            event="finished",
            model="celery",
            task_id=task_id,
            item_id=item.id,
            template_id=task.template_id,
            tenant_id=item.tenant_id,
            status=item.status,
            success=item.status not in {FAILED, CANCELLED},
            latency_ms=(datetime.now(timezone.utc) - item_started).total_seconds() * 1000,
            metadata={"item_index": item_index},
        )

        return {
            "task_id": task_id,
            "item_index": item_index,
            "status": item.status,
            "content_id": item.content_id,
        }

    finally:
        session.close()


def _update_parent_task_progress(session, task_id: str):
    """原子性更新父任务进度与状态。"""
    # 统计各状态 item 数量
    items = session.query(GenerationTaskItem).filter(GenerationTaskItem.task_id == task_id).all()
    if not items:
        return

    total = len(items)
    succeeded = sum(1 for i in items if i.status == SUCCEEDED)
    failed = sum(1 for i in items if i.status == FAILED)
    awaiting = sum(1 for i in items if i.status == "awaiting_review")
    cancelled = sum(1 for i in items if i.status == CANCELLED)
    finished = succeeded + failed + awaiting + cancelled

    # 更新父任务
    task = session.query(GenerationTask).filter(GenerationTask.id == task_id).first()
    if not task:
        return

    task.progress = round(finished / total, 4)

    # 判断最终状态
    if finished == total:
        # 全部完成
        if cancelled == total:
            task.status = CANCELLED
        elif failed == 0:
            task.status = SUCCEEDED if awaiting == 0 else PARTIALLY_SUCCEEDED
        else:
            task.status = PARTIALLY_SUCCEEDED if succeeded > 0 else FAILED

        # 任务结束时生成站内通知
        notify_task_result(session, task)

    session.commit()

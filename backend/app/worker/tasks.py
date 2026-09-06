# app/worker/tasks.py —— Celery 批量生成任务
from celery import shared_task
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import SessionLocal
from app.models import GenerationTask
from app.notification import notify_task_result
from app.workflow.graph import run_generation

# 任务状态常量
PENDING = "pending"
RUNNING = "running"
PARTIALLY_SUCCEEDED = "partially_succeeded"
SUCCEEDED = "succeeded"
FAILED = "failed"


@shared_task(
    name="app.worker.tasks.process_generation_task",
    bind=True,
    # 可靠性（P0-6）：仅对瞬态基础设施错误自动重试；业务异常（生成耗尽等）
    # 不重试，维持部分成功聚合语义。重投/重试的幂等性由 PostgresSaver
    # 的 thread 级检查点保证（已完成条目不重复生成）。
    max_retries=settings.TASK_MAX_RETRIES,
    autoretry_for=(RedisConnectionError, RedisTimeoutError, OperationalError),
    retry_backoff=True,
    default_retry_delay=60,
    acks_late=True,
)
def process_generation_task(self, task_id: str) -> dict:
    """批量生成任务：读取任务，按 quantity 逐个调用 run_generation，更新进度与状态。

    并发控制：通过 worker 启动参数 --concurrency=5 限制并发；
    每个子任务独立提交，单条失败不中断整体，最终汇总部分成功/成功/失败。
    """
    session = SessionLocal()
    try:
        task = session.query(GenerationTask).filter(GenerationTask.id == task_id).first()
        if task is None:
            return {"task_id": task_id, "status": FAILED, "reason": "任务不存在"}

        # 标记执行中
        task.status = RUNNING
        session.commit()

        quantity = task.quantity
        succeeded = 0
        failed = 0
        awaiting = 0
        failed_reasons: list[str] = []

        for idx in range(quantity):
            # 每个子任务使用独立线程标识，便于断点续跑
            thread_id = f"{task_id}:{idx}"
            try:
                result = run_generation(
                    task_id=task_id,
                    template_id=task.template_id,
                    params=task.params,
                    session=session,
                    thread_id=thread_id,
                )
                if result.get("__interrupt__"):
                    # 灰区人工卡点（P1-1）：条目已落库 awaiting_review，等待人工裁决，
                    # 不计入成功也不算失败
                    awaiting += 1
                else:
                    succeeded += 1
            except Exception as exc:  # noqa: BLE001 —— 单条失败需捕获以继续
                failed += 1
                failed_reasons.append(str(exc))
            finally:
                # 每完成一条更新进度
                task.progress = round((idx + 1) / quantity, 4)
                session.commit()

        # 汇总状态：存在人工待裁决条目时任务未完全结束，按部分成功处理
        if failed == 0:
            task.status = SUCCEEDED if awaiting == 0 else PARTIALLY_SUCCEEDED
        else:
            task.status = PARTIALLY_SUCCEEDED if succeeded > 0 else FAILED
        session.commit()

        # 任务结束时生成站内通知
        notify_task_result(session, task)

        return {
            "task_id": task_id,
            "status": task.status,
            "total": quantity,
            "succeeded": succeeded,
            "failed": failed,
            "awaiting": awaiting,
            "failed_reasons": failed_reasons[:5],
        }
    finally:
        session.close()

# app/worker/celery_app.py —— Celery 应用实例
import logging

from celery import Celery
from celery.signals import worker_ready

from app.config import settings

logger = logging.getLogger("app.worker.celery_app")

# 创建 Celery 应用，broker/backend 均使用 Redis
celery_app = Celery(
    "english_edit",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# 任务模块自动发现
celery_app.autodiscover_tasks(["app.worker"])

# 基础配置
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 并发控制：worker 并发数由启动参数 --concurrency=5 控制，
    # 此处设置每个 worker 同时占用的 DB 连接上限，避免连接池耗尽
    worker_prefetch_multiplier=1,
    # 防挂起：软超时触发 SoftTimeLimitExceeded（可捕获做收尾），硬超时强制终止任务，
    # 避免单个任务卡死长期占用 worker，保证大批量任务不因个别异常整体阻塞
    task_soft_time_limit=600,
    task_time_limit=900,
    # 可靠投递（P0-6）：执行完成才 ack；worker 崩溃时消息重投而非丢失。
    # 重投幂等性由 PostgresSaver 的 thread 级检查点保证（已完成条目不重复生成）。
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # redis 未 ack 消息的可见性超时，须大于硬超时(900s)+重试延迟之和，防提前重投
    broker_transport_options={"visibility_timeout": 3600},
)


@worker_ready.connect
def _recover_stale_tasks_on_startup(**_kwargs):
    """worker 启动时恢复僵尸任务：running 且超时的任务重置为 pending 并重新入队。

    恢复失败仅告警，不阻断 worker 启动。
    """
    from app.database import SessionLocal
    from app.worker.recovery import recover_stale_tasks

    session = SessionLocal()
    try:
        recovered = recover_stale_tasks(session)
        if recovered:
            logger.warning("启动恢复僵尸任务 %d 个（重置 pending 并重新入队）", recovered)
    except Exception:  # noqa: BLE001 —— 恢复失败不阻断 worker 启动
        logger.warning("僵尸任务恢复失败", exc_info=True)
    finally:
        session.close()

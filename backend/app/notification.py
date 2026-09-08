# app/notification.py —— 站内消息通知服务
# 在任务完成/失败、内容被人工驳回等事件点生成站内信并落库。
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AppNotification, ContentItem, GenerationTask


def build_task_notification(task: GenerationTask) -> Optional[AppNotification]:
    """按任务状态构造站内通知对象（succeeded/partially_succeeded/failed）。

    纯逻辑，供单测；返回 None 表示该状态无需通知。
    """
    if task.status == "succeeded":
        ntype, title = "task_succeeded", "生成任务完成"
        content = f"任务 {task.id} 已成功生成 {task.quantity} 条内容"
    elif task.status == "partially_succeeded":
        ntype, title = "task_partial", "生成任务部分成功"
        content = f"任务 {task.id} 部分成功，部分条目生成失败"
    elif task.status == "failed":
        ntype, title = "task_failed", "生成任务失败"
        content = f"任务 {task.id} 生成失败"
    else:
        return None
    return AppNotification(
        type=ntype,
        title=title,
        content=content,
        related_id=task.id,
        event_id=f"task:{task.id}:result",
        tenant_id=task.tenant_id,
    )


def notify_task_result(db: Session, task: GenerationTask) -> None:
    """任务结束时按状态生成一条站内通知（succeeded/partially_succeeded/failed）。"""
    notification = build_task_notification(task)
    if notification is None:
        return
    if (
        notification.event_id
        and db.query(AppNotification)
        .filter(AppNotification.event_id == notification.event_id)
        .first()
    ):
        return
    db.add(notification)
    db.commit()


def notify_content_rejected(db: Session, item: ContentItem, reason: str = "") -> None:
    """人工质检驳回时生成一条站内通知。"""
    event_id = f"content:{item.id}:rejected"
    if db.query(AppNotification).filter(AppNotification.event_id == event_id).first():
        return
    db.add(
        AppNotification(
            type="content_rejected",
            title="内容被驳回",
            content=f"内容 {item.id} 被人工质检驳回" + (f"：{reason}" if reason else ""),
            related_id=item.id,
            event_id=event_id,
            tenant_id=item.tenant_id,
        )
    )
    db.commit()


def notify_human_review(db: Session, item: ContentItem, qc_score: float = 0.0) -> None:
    """灰区内容转入人工审核时生成一条站内通知（P1-1 人工卡点）。"""
    event_id = f"content:{item.id}:awaiting-review"
    if db.query(AppNotification).filter(AppNotification.event_id == event_id).first():
        return
    db.add(
        AppNotification(
            type="content_awaiting_review",
            title="内容待人工审核",
            content=f"内容 {item.id} 自动质检 {qc_score:g} 分，处于灰区，等待人工裁决",
            related_id=item.id,
            event_id=event_id,
            tenant_id=item.tenant_id,
        )
    )
    db.commit()

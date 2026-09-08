"""
AppNotification Service Layer
负责站内通知的业务逻辑
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import AppNotification, User


class NotificationService:
    """通知服务"""

    def __init__(self, db: Session):
        self.db = db

    def list_notifications(self, user: User, skip: int = 0, limit: int = 50) -> dict:
        """
        列出用户的通知

        权限：仅返回 user_id 匹配的通知
        """
        notifications = (
            self.db.query(AppNotification)
            .filter(AppNotification.user_id == user.id)
            .order_by(AppNotification.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        total = (
            self.db.query(func.count(AppNotification.id))
            .filter(AppNotification.user_id == user.id)
            .scalar()
            or 0
        )

        items = []
        for notif in notifications:
            items.append(
                {
                    "id": notif.id,
                    "type": notif.type,
                    "title": notif.title,
                    "content": notif.content,
                    "is_read": notif.is_read,
                    "created_at": notif.created_at.isoformat(),
                }
            )

        return {"items": items, "total": total, "skip": skip, "limit": limit}

    def get_unread_count(self, user: User) -> int:
        """
        获取未读通知数

        权限：仅统计 user_id 匹配的通知
        """
        return (
            self.db.query(func.count(AppNotification.id))
            .filter(AppNotification.user_id == user.id)
            .filter(AppNotification.is_read.is_(False))
            .scalar()
            or 0
        )

    def mark_as_read(self, notification_id: str, user: User) -> dict:
        """
        标记通知为已读

        权限：验证通知所属 user_id
        """
        notif = self.db.query(AppNotification).filter(AppNotification.id == notification_id).first()

        if not notif:
            raise NotFoundError(f"AppNotification not found: {notification_id}")

        # 权限校验
        if notif.user_id != user.id:
            from app.errors import TenantScopeDeniedError

            raise TenantScopeDeniedError("Cannot access AppNotification of another user")

        notif.is_read = True
        self.db.commit()
        self.db.refresh(notif)

        return {
            "id": notif.id,
            "type": notif.type,
            "title": notif.title,
            "content": notif.content,
            "is_read": notif.is_read,
            "created_at": notif.created_at.isoformat(),
        }

    def mark_all_as_read(self, user: User) -> int:
        """
        标记所有未读通知为已读

        权限：仅操作 user_id 匹配的通知
        """
        updated = (
            self.db.query(AppNotification)
            .filter(AppNotification.user_id == user.id)
            .filter(AppNotification.is_read.is_(False))
            .update({"is_read": True}, synchronize_session=False)
        )
        self.db.commit()

        return updated

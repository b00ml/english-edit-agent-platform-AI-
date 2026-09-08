"""
用户 Repository
职责：用户数据访问、查询
"""

from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """用户数据访问层。"""

    def __init__(self, db: Session):
        super().__init__(User, db)

    def get_by_username(self, username: str) -> Optional[User]:
        """根据用户名查询。"""
        return self.db.query(User).filter(User.username == username).first()

    def get_by_email(self, email: str) -> Optional[User]:
        """根据邮箱查询。"""
        return self.db.query(User).filter(User.email == email).first()

    def list_by_role(self, role: str, skip: int = 0, limit: int = 100) -> List[User]:
        """按角色查询用户。"""
        return self.db.query(User).filter(User.role == role).offset(skip).limit(limit).all()

    def list_by_tenant(self, tenant_id: int, skip: int = 0, limit: int = 100) -> List[User]:
        """按租户查询用户。"""
        return (
            self.db.query(User).filter(User.tenant_id == tenant_id).offset(skip).limit(limit).all()
        )

    def count_by_tenant(self, tenant_id: int) -> int:
        """统计租户用户数。"""
        return self.db.query(func.count(User.id)).filter(User.tenant_id == tenant_id).scalar()

    def exists_username(self, username: str) -> bool:
        """检查用户名是否存在。"""
        return self.db.query(User.id).filter(User.username == username).first() is not None

    def exists_email(self, email: str) -> bool:
        """检查邮箱是否存在。"""
        return self.db.query(User.id).filter(User.email == email).first() is not None

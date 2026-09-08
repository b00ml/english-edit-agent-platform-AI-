"""
认证 Service
职责：用户登录、JWT 签发、用户创建与管理
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User
from app.repositories import UserRepository
from app.schemas import LoginOut, UserCreateIn, UserOut, UserUpdateIn
from app.security import create_access_token, hash_password, verify_password


class AuthService:
    """认证业务逻辑层。"""

    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)

    def login(self, username: str, password: str) -> LoginOut:
        """用户登录，返回 JWT token。"""
        user = self.user_repo.get_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if user.status != "active":
            raise HTTPException(status_code=401, detail="账号已被禁用")

        token = create_access_token(user)
        return LoginOut(
            access_token=token,
            user=UserOut.model_validate(user),
        )

    def create_user(
        self, data: UserCreateIn, operator_id: str, tenant_id: Optional[str] = None
    ) -> User:
        """创建用户（管理员操作）。"""
        # 检查用户名是否已存在
        if self.user_repo.exists_username(data.username):
            raise HTTPException(status_code=400, detail="用户名已存在")

        # 创建用户
        user = self.user_repo.create(
            username=data.username,
            password_hash=hash_password(data.password),
            display_name=data.display_name or data.username,
            role=data.role,
            tenant_id=tenant_id,
            status="active",
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user(self, user_id: str, data: UserUpdateIn) -> User:
        """更新用户信息（管理员操作）。"""
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 更新字段
        update_data = data.model_dump(exclude_unset=True)
        if "password" in update_data:
            update_data["password_hash"] = hash_password(update_data.pop("password"))

        self.user_repo.update(user, **update_data)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        """获取用户详情。"""
        return self.user_repo.get_by_id(user_id)

    def list_users(
        self, tenant_id: Optional[str] = None, skip: int = 0, limit: int = 100
    ) -> tuple[list[User], int]:
        """查询用户列表。"""
        if tenant_id:
            users = self.user_repo.list_by_tenant(tenant_id, skip, limit)
            total = self.user_repo.count_by_tenant(tenant_id)
        else:
            users = self.user_repo.list_all(skip, limit)
            total = self.user_repo.count()
        return users, total

    def disable_user(self, user_id: str) -> User:
        """禁用用户。"""
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")

        self.user_repo.update(user, status="disabled")
        self.db.commit()
        self.db.refresh(user)
        return user

    def enable_user(self, user_id: str) -> User:
        """启用用户。"""
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")

        self.user_repo.update(user, status="active")
        self.db.commit()
        self.db.refresh(user)
        return user

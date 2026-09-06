# app/seed.py —— 启动时种子数据初始化（K4 权限）
# 职责：首次启动时自动写入默认管理员账号，避免新库无用户可用。
# 设计原则：幂等（idempotent）—— 已存在的账号不覆盖密码，仅补齐缺失的种子用户。
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.security import hash_password

logger = logging.getLogger("app.seed")


def seed_default_admin(session: Session) -> User | None:
    """确保至少存在一个管理员账号。

    规则：
      1. 若用户表为空 → 按配置写入默认管理员；
      2. 若默认管理员用户名已存在 → 不覆盖其密码（避免误改生产密码），仅补 display_name；
      3. 返回新建或已存在的管理员 User；若无需写入则返回 None。
    """
    username = settings.SEED_ADMIN_USERNAME
    password = settings.SEED_ADMIN_PASSWORD
    display_name = settings.SEED_ADMIN_DISPLAY_NAME

    existing = session.query(User).filter(User.username == username).first()
    if existing is not None:
        # 已存在：仅补齐 display_name，绝不覆盖密码
        if existing.display_name != display_name:
            existing.display_name = display_name
            session.commit()
            logger.info("已更新默认管理员 display_name（未覆盖密码）: %s", username)
        else:
            logger.info("默认管理员已存在，跳过种子写入: %s", username)
        return existing

    # 用户表无此管理员 → 新建
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role="admin",
        status="active",
    )
    session.add(user)
    session.commit()
    logger.warning(
        "已初始化默认管理员账号 [%s]（首次登录后请通过用户管理接口修改密码）",
        username,
    )
    return user

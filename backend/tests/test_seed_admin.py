# tests/test_seed_admin.py —— K4 权限：种子管理员账号 单测
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as ORMSession

from app.config import settings
from app.models import User
from app.security import hash_password, verify_password
from app.seed import seed_default_admin


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


@pytest.fixture
def empty_session():
    """返回含 users 表的空内存 SQLite 会话。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    User.__table__.create(bind=engine)
    with ORMSession(engine) as s:
        yield s


@pytest.fixture
def session_with_existing_admin():
    """返回已存在默认管理员的会话。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    User.__table__.create(bind=engine)
    with ORMSession(engine) as s:
        s.add(
            User(
                username=settings.SEED_ADMIN_USERNAME,
                password_hash=hash_password("custom_pass_123"),
                display_name="原管理员",
                role="admin",
                status="active",
            )
        )
        s.commit()
        yield s


# ---------------------------------------------------------------------------
# 空库首次初始化
# ---------------------------------------------------------------------------
class TestSeedOnEmpty:
    def test_creates_admin_with_config_credentials(self, empty_session):
        result = seed_default_admin(empty_session)
        assert result is not None
        assert result.username == settings.SEED_ADMIN_USERNAME
        assert result.display_name == settings.SEED_ADMIN_DISPLAY_NAME
        assert result.role == "admin"
        assert result.status == "active"
        assert verify_password(settings.SEED_ADMIN_PASSWORD, result.password_hash)

    def test_idempotent_second_call_no_duplicate(self, empty_session):
        seed_default_admin(empty_session)
        seed_default_admin(empty_session)
        count = empty_session.query(User).count()
        assert count == 1

    def test_other_users_not_affected(self, empty_session):
        """种子管理员写入后，新增其他用户不应被干扰。"""
        seed_default_admin(empty_session)
        empty_session.add(
            User(
                username="researcher1",
                password_hash=hash_password("r1pass"),
                display_name="教研员",
                role="researcher",
                status="active",
            )
        )
        empty_session.commit()
        count = empty_session.query(User).count()
        assert count == 2
        admin = empty_session.query(User).filter(User.role == "admin").one()
        assert admin.username == settings.SEED_ADMIN_USERNAME


# ---------------------------------------------------------------------------
# 已存在管理员：不覆盖密码
# ---------------------------------------------------------------------------
class TestSeedExisting:
    def test_does_not_overwrite_password(self, session_with_existing_admin):
        original = (
            session_with_existing_admin.query(User)
            .filter(User.username == settings.SEED_ADMIN_USERNAME)
            .one()
        )
        original_hash = original.password_hash

        seed_default_admin(session_with_existing_admin)

        after = (
            session_with_existing_admin.query(User)
            .filter(User.username == settings.SEED_ADMIN_USERNAME)
            .one()
        )
        assert after.password_hash == original_hash
        assert verify_password("custom_pass_123", after.password_hash)

    def test_updates_display_name_when_differs(self, session_with_existing_admin):
        """display_name 与配置不一致时自动更新（但仍不覆盖密码）。"""
        seed_default_admin(session_with_existing_admin)
        after = (
            session_with_existing_admin.query(User)
            .filter(User.username == settings.SEED_ADMIN_USERNAME)
            .one()
        )
        assert after.display_name == settings.SEED_ADMIN_DISPLAY_NAME

    def test_returns_existing_user(self, session_with_existing_admin):
        result = seed_default_admin(session_with_existing_admin)
        assert result is not None
        assert result.username == settings.SEED_ADMIN_USERNAME
        count = session_with_existing_admin.query(User).count()
        assert count == 1


# ---------------------------------------------------------------------------
# 种子配置值来自环境变量（集成 settings）
# ---------------------------------------------------------------------------
class TestSeedConfig:
    def test_uses_configured_username(self, empty_session):
        assert settings.SEED_ADMIN_USERNAME == "admin"
        user = seed_default_admin(empty_session)
        assert user.username == "admin"

    def test_password_is_hashed(self, empty_session):
        """密码以哈希存储，而非明文。"""
        user = seed_default_admin(empty_session)
        assert user.password_hash != settings.SEED_ADMIN_PASSWORD
        assert "admin123" not in user.password_hash

# tests/test_security.py —— K4 权限：密码哈希 / JWT / 权限矩阵 纯逻辑单测
import time

import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as ORMSession

from app.config import settings
from app.models import User
from app.security import (
    create_access_token,
    decode_access_token,
    has_permission,
    hash_password,
    verify_password,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    """SQLite 测试环境将 JSONB 编译为 JSON，便于内存表建表。"""
    return "JSON"


@pytest.fixture
def session():
    """返回含 users 表的内存 SQLite 会话。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    User.__table__.create(bind=engine)
    with ORMSession(engine) as s:
        s.add(
            User(
                id="u-admin",
                username="admin",
                password_hash=hash_password("admin123"),
                display_name="管理员",
                role="admin",
                status="active",
            )
        )
        s.add(
            User(
                id="u-reviewer",
                username="rev",
                password_hash=hash_password("rev123"),
                display_name="质检员",
                role="reviewer",
                status="active",
            )
        )
        s.add(
            User(
                id="u-disabled",
                username="off",
                password_hash=hash_password("off123"),
                display_name="禁用",
                role="researcher",
                status="disabled",
            )
        )
        s.commit()
        yield s


def _user(session, uid: str) -> User:
    return session.get(User, uid)


# ---------------------------------------------------------------------------
# 密码哈希 / 校验
# ---------------------------------------------------------------------------
class TestPassword:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("secret123")
        assert hashed != "secret123"
        assert "secret123" not in hashed

    def test_verify_correct_password(self):
        hashed = hash_password("secret123")
        assert verify_password("secret123", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("secret123")
        assert verify_password("wrong", hashed) is False

    def test_verify_invalid_hash_returns_false(self):
        # 异常哈希不应抛异常，而是返回 False
        assert verify_password("x", "not-a-valid-hash") is False


# ---------------------------------------------------------------------------
# JWT 签发 / 解析
# ---------------------------------------------------------------------------
class TestJWT:
    def test_token_roundtrip(self, session):
        user = _user(session, "u-admin")
        token = create_access_token(user)
        payload = decode_access_token(token)
        assert payload["sub"] == user.id
        assert payload["role"] == "admin"
        assert payload["username"] == "admin"

    def test_expired_token_rejected(self, session):
        user = _user(session, "u-admin")
        token = create_access_token(user)
        # 篡改 exp 为过去时间，强制过期
        forged = jwt.encode(
            {"sub": user.id, "exp": int(time.time()) - 10},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        with pytest.raises(Exception):
            decode_access_token(forged)

    def test_invalid_signature_rejected(self):
        bad = jwt.encode({"sub": "x"}, "wrong-secret", algorithm="HS256")
        with pytest.raises(Exception):
            decode_access_token(bad)


# ---------------------------------------------------------------------------
# 权限矩阵
# ---------------------------------------------------------------------------
class TestPermission:
    def test_admin_has_all_manage(self, session):
        assert has_permission(_user(session, "u-admin"), "user:manage")
        assert has_permission(_user(session, "u-admin"), "template:manage")
        assert has_permission(_user(session, "u-admin"), "generate:create")
        assert has_permission(_user(session, "u-admin"), "content:publish")
        assert has_permission(_user(session, "u-admin"), "ops:write")

    def test_reviewer_can_review_but_not_manage(self, session):
        u = _user(session, "u-reviewer")
        assert has_permission(u, "quality:review")
        assert has_permission(u, "content:read")
        assert not has_permission(u, "user:manage")
        assert not has_permission(u, "generate:create")
        assert not has_permission(u, "ops:write")

    def test_disabled_user_loses_all_permissions(self, session):
        u = _user(session, "u-disabled")
        assert has_permission(u, "generate:create") is False

    def test_unknown_permission_denied(self, session):
        assert has_permission(_user(session, "u-admin"), "not:a:perm") is False

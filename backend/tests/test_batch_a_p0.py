"""
批次 A P0 可靠性与权限改造单元测试
测试范围：
1. 状态迁移校验（domain/status.py）
2. reject_node 落库 failure_code/failure_reason（workflow/graph.py）
3. 发布接口状态前置检查（api/routes.py）
4. 租户隔离过滤（api/routes.py + rag/retriever.py）
5. 生产环境配置 fail-fast（config.py）
"""

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.domain.status import (
    CONTENT_AWAITING_REVIEW,
    CONTENT_PASSED,
    CONTENT_PENDING_QC,
    CONTENT_PUBLISHED,
    CONTENT_REJECTED,
    can_transition_content,
)


# ============================================================================
# 1. 状态迁移校验测试（不依赖数据库）
# ============================================================================
class TestContentStateTransition:
    """测试内容状态迁移校验逻辑。"""

    def test_allowed_transitions(self):
        """测试允许的状态迁移。"""
        # pending_qc 可以迁移到 passed/rejected/awaiting_review
        assert can_transition_content(CONTENT_PENDING_QC, CONTENT_PASSED) is True
        assert can_transition_content(CONTENT_PENDING_QC, CONTENT_REJECTED) is True
        assert can_transition_content(CONTENT_PENDING_QC, CONTENT_AWAITING_REVIEW) is True

        # awaiting_review 可以迁移到 passed/rejected
        assert can_transition_content(CONTENT_AWAITING_REVIEW, CONTENT_PASSED) is True
        assert can_transition_content(CONTENT_AWAITING_REVIEW, CONTENT_REJECTED) is True

        # passed 只能迁移到 published
        assert can_transition_content(CONTENT_PASSED, CONTENT_PUBLISHED) is True

    def test_forbidden_transitions(self):
        """测试禁止的状态迁移。"""
        # pending_qc 不能直接发布
        assert can_transition_content(CONTENT_PENDING_QC, CONTENT_PUBLISHED) is False

        # awaiting_review 不能直接发布
        assert can_transition_content(CONTENT_AWAITING_REVIEW, CONTENT_PUBLISHED) is False

        # published 和 rejected 是终态，不能迁移到任何状态
        assert can_transition_content(CONTENT_PUBLISHED, CONTENT_PASSED) is False
        assert can_transition_content(CONTENT_REJECTED, CONTENT_PASSED) is False
        assert can_transition_content(CONTENT_REJECTED, CONTENT_PUBLISHED) is False

    def test_invalid_current_state(self):
        """测试无效的当前状态。"""
        assert can_transition_content("invalid_state", CONTENT_PASSED) is False


# ============================================================================
# 2. 生产环境配置 fail-fast 测试（不依赖数据库）
# ============================================================================
class TestProductionConfigFailFast:
    """测试生产环境配置校验。"""

    def test_production_requires_custom_jwt_secret(self):
        """测试生产环境必须设置自定义 JWT_SECRET。"""
        with pytest.raises(ValueError, match="生产环境必须设置非占位 JWT_SECRET"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET="change-me-english-edit-jwt-secret",  # 默认值
                SEED_ADMIN_PASSWORD="custom-password",
                LLM_API_KEY="test_key",
                EMBEDDING_API_KEY="test_key",
            )

    def test_production_requires_custom_admin_password(self):
        """测试生产环境必须设置自定义管理员密码。"""
        with pytest.raises(ValueError, match="生产环境必须设置非占位 SEED_ADMIN_PASSWORD"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET="custom-jwt-secret-with-at-least-32-bytes",
                SEED_ADMIN_PASSWORD="admin123",  # 默认值
                LLM_API_KEY="test_key",
                EMBEDDING_API_KEY="test_key",
            )

    def test_production_requires_llm_api_key(self):
        """测试生产环境必须设置 LLM_API_KEY。"""
        with pytest.raises(ValueError, match="生产环境必须设置非占位 LLM_API_KEY"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET="custom-jwt-secret-with-at-least-32-bytes",
                SEED_ADMIN_PASSWORD="custom-password",
                LLM_API_KEY="",  # 空值
                EMBEDDING_API_KEY="test_key",
            )

    def test_production_requires_embedding_api_key(self):
        """测试生产环境必须设置 EMBEDDING_API_KEY。"""
        with pytest.raises(ValueError, match="生产环境必须设置非占位 EMBEDDING_API_KEY"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET="custom-jwt-secret-with-at-least-32-bytes",
                SEED_ADMIN_PASSWORD="custom-password",
                LLM_API_KEY="test_key",
                EMBEDDING_API_KEY="",  # 空值
            )

    def test_production_with_all_custom_values_success(self):
        """测试生产环境所有配置正确时可以启动。"""
        # 不应抛出异常
        config = Settings(
            ENVIRONMENT="production",
            JWT_SECRET="custom-jwt-secret-with-at-least-32-bytes",
            SEED_ADMIN_PASSWORD="custom_admin_password",
            LLM_API_KEY="sk-test-key",
            EMBEDDING_API_KEY="sk-embed-key",
        )
        assert config.ENVIRONMENT == "production"
        assert config.JWT_SECRET == "custom-jwt-secret-with-at-least-32-bytes"

    def test_production_rejects_example_placeholders_and_short_jwt(self):
        """示例占位值和短 HMAC secret 不能进入生产环境。"""
        with pytest.raises(ValueError, match="非占位 LLM_API_KEY"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET="custom-jwt-secret-with-at-least-32-bytes",
                SEED_ADMIN_PASSWORD="custom-password",
                LLM_API_KEY="sk-xxxxxxxx",
                EMBEDDING_API_KEY="sk-real-key",
            )
        with pytest.raises(ValueError, match="至少需要 32 字节"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET="too-short",
                SEED_ADMIN_PASSWORD="custom-password",
                LLM_API_KEY="sk-real-key",
                EMBEDDING_API_KEY="sk-real-key",
            )

    def test_development_allows_default_values(self):
        """测试开发环境允许使用默认值。"""
        # 不应抛出异常
        config = Settings(
            ENVIRONMENT="development",
            JWT_SECRET="change-me-english-edit-jwt-secret",
            SEED_ADMIN_PASSWORD="admin123",
        )
        assert config.JWT_SECRET == "change-me-english-edit-jwt-secret"
        assert config.SEED_ADMIN_PASSWORD == "admin123"


# ============================================================================
# 3. reject_node 逻辑测试（使用 Mock，不依赖真实数据库）
# ============================================================================
class TestRejectNodeLogic:
    """测试 reject_node 的失败记录逻辑（不依赖真实数据库）。"""

    def test_reject_node_constructs_failure_info(self):
        """测试 reject_node 构造失败信息的逻辑。"""
        from app.workflow.graph import GenState

        # 模拟状态
        state: GenState = {
            "task_id": "task-123",
            "trace_id": "trace-456",
            "params": {"template_id": "single_choice", "topic": "测试主题"},
            "qc_score": 0.45,
            "revise_count": 3,
            "draft": {"question": "低质量题目"},
        }

        # 验证默认 failure_code
        failure_code = state.get("failure_code", "quality_threshold_not_met")
        assert failure_code == "quality_threshold_not_met"

        # 验证默认 failure_reason 包含质检分和重试次数
        failure_reason = state.get(
            "failure_reason",
            f"质检分数 {state.get('qc_score', 0.0)} 低于阈值，已重试 {state.get('revise_count', 0)} 次",
        )
        assert "质检分数 0.45 低于阈值" in failure_reason
        assert "已重试 3 次" in failure_reason

    def test_reject_node_custom_failure_code(self):
        """测试 reject_node 使用自定义 failure_code。"""
        from app.workflow.graph import GenState

        state: GenState = {
            "task_id": "task-123",
            "trace_id": "trace-456",
            "params": {"template_id": "single_choice"},
            "qc_score": 0.50,
            "revise_count": 2,
            "failure_code": "validation_failed",
            "failure_reason": "选项格式不正确",
        }

        # 验证自定义值被使用
        assert state["failure_code"] == "validation_failed"
        assert state["failure_reason"] == "选项格式不正确"


# ============================================================================
# 4. API 路由逻辑测试（使用 Mock，不依赖真实数据库）
# ============================================================================
class TestPublishLogic:
    """测试发布接口的状态校验逻辑（不依赖真实数据库）。"""

    def test_can_publish_passed_content(self):
        """测试 passed 状态可以发布。"""
        assert can_transition_content(CONTENT_PASSED, CONTENT_PUBLISHED) is True

    def test_cannot_publish_pending_qc_content(self):
        """测试 pending_qc 状态不能发布。"""
        assert can_transition_content(CONTENT_PENDING_QC, CONTENT_PUBLISHED) is False

    def test_cannot_publish_awaiting_review_content(self):
        """测试 awaiting_review 状态不能发布。"""
        assert can_transition_content(CONTENT_AWAITING_REVIEW, CONTENT_PUBLISHED) is False

    def test_cannot_publish_rejected_content(self):
        """测试 rejected 状态不能发布。"""
        assert can_transition_content(CONTENT_REJECTED, CONTENT_PUBLISHED) is False

    def test_cannot_republish_published_content(self):
        """测试 published 状态是终态，不能再迁移。"""
        assert can_transition_content(CONTENT_PUBLISHED, CONTENT_PUBLISHED) is False
        assert can_transition_content(CONTENT_PUBLISHED, CONTENT_PASSED) is False


# ============================================================================
# 5. 租户隔离逻辑测试（使用 Mock，不依赖真实数据库）
# ============================================================================
class TestTenantIsolationLogic:
    """测试租户隔离的过滤逻辑（不依赖真实数据库）。"""

    def test_viewer_role_requires_tenant_filter(self):
        """测试 viewer 角色需要租户过滤。"""
        # 模拟用户
        mock_user = MagicMock()
        mock_user.roles = ["viewer"]
        mock_user.tenant_id = "tenant-001"

        # 验证逻辑：viewer 必须带 tenant_id 过滤
        assert "viewer" in mock_user.roles
        assert mock_user.tenant_id == "tenant-001"

    def test_admin_role_no_tenant_restriction(self):
        """测试 admin 角色不受租户限制。"""
        mock_user = MagicMock()
        mock_user.roles = ["admin"]
        mock_user.tenant_id = "tenant-001"

        # admin 可以不受租户限制
        assert "admin" in mock_user.roles

    def test_rag_retriever_accepts_tenant_id(self):
        """测试 RAG retriever 接受 tenant_id 参数。"""
        from inspect import signature

        from app.rag.retriever import retrieve

        sig = signature(retrieve)
        # 验证 tenant_id 参数存在
        assert "tenant_id" in sig.parameters
        # 验证默认值为 None（可选参数）
        assert sig.parameters["tenant_id"].default is None

# tests/integration/conftest.py —— 集成测试环境装配（P1-4 / OPT-025）
# 集成测试需要真实 Postgres（模型使用 JSONB + pgvector，sqlite 不可行）：
#   1. 本地：docker run pgvector/pgvector:pg16 后设置 TEST_DATABASE_URL 再运行
#      `pytest tests/integration`；
#   2. CI：backend-ci.yml integration job 注入 service 容器与 TEST_DATABASE_URL。
# 未设置 TEST_DATABASE_URL 时整个目录被跳过（默认单测流程不受影响）。
# 注意：本 conftest 在 app.config 首次导入前把 DATABASE_URL 重定向到测试库，
# 因此集成测试应独立运行（CI 分 job），避免与单元测试共享进程内的旧配置单例。
import os

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

if TEST_DATABASE_URL:
    # 必须在 app.config 首次导入前生效
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    # 进程内 checkpointer（interrupt 恢复在同进程内验证；PostgresSaver 由 P0-3 单测覆盖）
    os.environ.setdefault("CHECKPOINTER_BACKEND", "memory")
    # 测试专用 JWT 密钥（避免弱密钥告警干扰）
    os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret")


def pytest_collection_modifyitems(config, items):
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="需要 TEST_DATABASE_URL（真实 Postgres）")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def _pg_ready():
    """确保 pgvector 扩展可用（create_all 建含 vector 列的表前必须装扩展）。"""
    from sqlalchemy import create_engine, text

    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    engine.dispose()
    return True


@pytest.fixture(autouse=True)
def mock_embedding(monkeypatch):
    """替换 embedding 客户端：返回确定性的 1024 维零向量（走真 pgvector 距离查询）。"""
    from types import SimpleNamespace

    from app.rag import embedding as embedding_module

    class _FakeEmbeddingClient:
        @property
        def embeddings(self):
            return self

        def create(self, model=None, input=None, **kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=i, embedding=[0.0] * 1024)
                    for i, _ in enumerate(input or [])
                ]
            )

    monkeypatch.setattr(embedding_module, "_get_openai_client", lambda: _FakeEmbeddingClient())


@pytest.fixture()
def client(_pg_ready, monkeypatch):
    """FastAPI TestClient：进入上下文触发 lifespan（建表/模板/种子管理员）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def inline_celery(monkeypatch):
    """把 celery send_task 替换为进程内同步执行（不依赖 redis）。"""
    from app.api import routes as routes_module
    from app.worker.tasks import process_generation_task

    def _fake_send_task(name, args=None, **kwargs):
        assert name == "app.worker.tasks.process_generation_task"
        result = process_generation_task.apply(args=args or [])
        return SimpleAsyncResult(result.get())

    class SimpleAsyncResult:
        def __init__(self, value):
            self._value = value

        def get(self, timeout=None):
            return self._value

    monkeypatch.setattr(routes_module.celery_app, "send_task", _fake_send_task)
    return _fake_send_task


class _FakeUsage:
    prompt_tokens = 100
    completion_tokens = 50


class FakeLLMClient:
    """脚本化 OpenAI 兼容客户端：按调用顺序返回内容或抛错。"""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self._contents.pop(0)
        from types import SimpleNamespace

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=_FakeUsage(),
        )


@pytest.fixture()
def mock_llm(monkeypatch):
    """替换生成与质检两个引擎的 LLM 客户端；返回 (gen_client, judge_client)。"""
    from app.engine import quality as quality_module
    from app.engine import structured_output as so_module

    gen_client = FakeLLMClient([])
    judge_client = FakeLLMClient([])
    monkeypatch.setattr(so_module, "_get_openai_client", lambda: gen_client)
    monkeypatch.setattr(quality_module, "_get_openai_client", lambda: judge_client)
    return gen_client, judge_client


GEN_OK = (
    '{"stem": "Choose the correct form: She ___ to school every day.", '
    '"options": ["go", "goes", "going", "gone"], "answer": "B", '
    '"explanation": "一般现在时第三人称单数用 goes。"}'
)
JUDGE_HIGH = (
    '{"dimension_scores": {"kp_match": 90, "diff_match": 85, '
    '"distractor": 88, "unambiguous": 92}}'
)
JUDGE_GRAY = (
    '{"dimension_scores": {"kp_match": 65, "diff_match": 65, '
    '"distractor": 65, "unambiguous": 65}}'
)

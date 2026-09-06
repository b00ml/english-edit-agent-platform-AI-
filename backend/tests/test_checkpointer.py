# tests/test_checkpointer.py —— checkpointer 后端选择单测（P0-3 / OPT-018）
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.workflow.graph import _get_checkpointer, build_graph, reset_checkpointer


@pytest.fixture(autouse=True)
def _fresh_checkpointer():
    reset_checkpointer()
    yield
    reset_checkpointer()


class TestCheckpointerBackend:
    def test_memory_backend(self, monkeypatch):
        monkeypatch.setattr(settings, "CHECKPOINTER_BACKEND", "memory")
        cp = _get_checkpointer()
        assert isinstance(cp, MemorySaver)

    def test_singleton_reused(self, monkeypatch):
        monkeypatch.setattr(settings, "CHECKPOINTER_BACKEND", "memory")
        assert _get_checkpointer() is _get_checkpointer()

    def test_postgres_connect_failure_falls_back_to_memory(self, monkeypatch):
        monkeypatch.setattr(settings, "CHECKPOINTER_BACKEND", "postgres")
        try:
            import psycopg  # noqa: F401
        except ImportError:
            pass  # 包未安装 -> ImportError -> 天然降级
        else:

            def _refuse(*args, **kwargs):
                raise psycopg.OperationalError("connection refused")

            monkeypatch.setattr(psycopg, "connect", _refuse)
        cp = _get_checkpointer()
        assert isinstance(cp, MemorySaver)

    def test_build_graph_uses_checkpointer(self, monkeypatch):
        monkeypatch.setattr(settings, "CHECKPOINTER_BACKEND", "memory")
        compiled = build_graph(None)  # 编译阶段不触库，节点闭包暂不用 session
        assert compiled.checkpointer is _get_checkpointer()

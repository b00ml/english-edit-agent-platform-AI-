# tests/test_router.py —— 模型路由与降级链单测
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as ORMSession

from app.engine import router as router_mod
from app.errors import ModelRoutingError
from app.models import ModelProfile


@pytest.fixture
def session():
    """返回含 model_profile 表的内存 SQLite 会话（standard=默认, lite=备用）。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    ModelProfile.__table__.create(bind=engine)
    with ORMSession(engine) as s:
        s.add_all(
            [
                ModelProfile(
                    id="p-standard",
                    name="standard",
                    provider="deepseek",
                    model_name="m1",
                    is_default=True,
                ),
                ModelProfile(
                    id="p-lite", name="lite", provider="qwen", model_name="m2", is_default=False
                ),
            ]
        )
        s.commit()
        yield s


class TestResolveModelProfile:
    def test_exact_match(self, session):
        p = router_mod.resolve_model_profile(session, "standard")
        assert p is not None and p.name == "standard"

    def test_fallback_to_default(self, session):
        p = router_mod.resolve_model_profile(session, "not_exist")
        assert p is not None and p.name == "standard"

    def test_none_returns_default(self, session):
        p = router_mod.resolve_model_profile(session, None)
        assert p is not None and p.name == "standard"


class _Template:
    def __init__(self, run_config=None):
        self.run_config = run_config or {}


def _mock_generate(monkeypatch, behavior):
    """fake_generate 依 candidate.model_name 查 behavior 表。

    behavior[model] 为 Exception 则抛出，否则返回该值；未命中一律抛错。
    内置默认兜底调用时 candidate 为 None，其 model_name 记作 None。
    """
    calls = []

    def fake_generate(template, params, candidate, **kwargs):
        model = getattr(candidate, "model_name", None)
        calls.append(model)
        if model in behavior:
            result = behavior[model]
            if isinstance(result, Exception):
                raise result
            return result
        raise RuntimeError(f"unexpected model: {model}")

    monkeypatch.setattr(router_mod, "generate_structured", fake_generate)
    return calls


class TestGenerateWithFallback:
    def test_primary_succeeds(self, session, monkeypatch):
        calls = _mock_generate(monkeypatch, {"m1": {"ok": True, "model": "m1"}})
        template = _Template({"model_profile": "standard"})
        out = router_mod.generate_with_fallback(template, {}, session)
        assert out["model"] == "m1"
        assert calls == ["m1"]

    def test_fallback_to_default_when_primary_fails(self, session, monkeypatch):
        calls = _mock_generate(
            monkeypatch,
            {"m2": RuntimeError("boom"), "m1": {"ok": True, "model": "m1"}},
        )
        template = _Template({"model_profile": "lite"})
        out = router_mod.generate_with_fallback(template, {}, session)
        # lite(m2) 失败 -> 降级到默认 standard(m1) 成功
        assert out["model"] == "m1"
        assert calls == ["m2", "m1"]

    def test_all_fail_raises_model_routing_error(self, session, monkeypatch):
        _mock_generate(
            monkeypatch,
            {
                "m2": RuntimeError("boom"),
                "m1": RuntimeError("boom"),
                None: RuntimeError("boom"),
            },
        )
        template = _Template({"model_profile": "lite"})
        with pytest.raises(ModelRoutingError):
            router_mod.generate_with_fallback(template, {}, session)


class TestDifficultyBasedRouting:
    """按难度分档路由：复杂阅读题走高性能模型，简单单选走 lite。"""

    def test_difficulty_maps_to_profile(self, session):
        run_config = {
            "model_profile": {
                "easy": "lite",
                "medium": "standard",
                "hard": "standard",
            }
        }
        assert (
            router_mod._resolve_primary_profile_name(run_config, {"difficulty": "easy"}) == "lite"
        )
        assert (
            router_mod._resolve_primary_profile_name(run_config, {"difficulty": "hard"})
            == "standard"
        )

    def test_missing_difficulty_falls_back_to_default(self, session):
        run_config = {"model_profile": {"default": "standard", "hard": "high"}}
        # 无难度默认走 default
        assert router_mod._resolve_primary_profile_name(run_config, {}) == "standard"

    def test_unknown_difficulty_falls_back_to_default(self, session):
        run_config = {"model_profile": {"default": "lite", "hard": "high"}}
        assert (
            router_mod._resolve_primary_profile_name(run_config, {"difficulty": "极难"}) == "lite"
        )

    def test_explicit_profile_overrides_run_config(self, session):
        run_config = {"model_profile": {"default": "lite"}}
        assert (
            router_mod._resolve_primary_profile_name(run_config, {}, profile_name="high") == "high"
        )

    def test_difficulty_routing_in_generate_with_fallback(self, session, monkeypatch):
        """复杂阅读（hard）应命中高性能模型 h1，而非默认 m1。"""
        # 新增一个高性能档案
        session.add(
            ModelProfile(
                id="p-high", name="high", provider="deepseek", model_name="h1", is_default=False
            )
        )
        session.commit()
        calls = _mock_generate(monkeypatch, {"h1": {"ok": True, "model": "h1"}})
        template = _Template({"model_profile": {"default": "standard", "hard": "high"}})
        out = router_mod.generate_with_fallback(template, {"difficulty": "hard"}, session)
        assert out["model"] == "h1"
        assert calls == ["h1"]

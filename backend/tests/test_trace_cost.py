# tests/test_trace_cost.py —— 深度成本 token 细分（P3/K2）纯逻辑单测
import pytest

from app.engine.trace import compute_cost, token_breakdown

# 每千 token 单价（与 config 默认一致）
_RATE = 0.002


class _Usage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class TestComputeCost:
    def test_cost_scales_with_tokens(self):
        cost = compute_cost(_Usage(1000, 1000), "qwen")
        # 2000 token @ 每千 token 单价 = 2 倍单价
        assert cost == pytest.approx(2 * _RATE, abs=1e-3)

    def test_cost_none_usage_zero(self):
        assert compute_cost(None, "qwen") == 0.0


class TestTokenBreakdown:
    def test_breakdown_splits_prompt_completion(self):
        bd = token_breakdown(_Usage(1000, 2000), "qwen")
        assert bd["prompt_tokens"] == 1000
        assert bd["completion_tokens"] == 2000
        assert bd["prompt_cost"] == pytest.approx(bd["prompt_tokens"] / 1000 * _RATE, abs=1e-3)
        assert bd["completion_cost"] == pytest.approx(
            bd["completion_tokens"] / 1000 * _RATE, abs=1e-3
        )
        # cost 等于输入+输出成本之和
        assert bd["cost"] == pytest.approx(bd["prompt_cost"] + bd["completion_cost"], abs=1e-6)

    def test_breakdown_none_usage_zero(self):
        bd = token_breakdown(None, "qwen")
        assert bd["prompt_tokens"] == 0
        assert bd["completion_tokens"] == 0
        assert bd["cost"] == 0.0


# ---------------------------------------------------------------------------
# P1-3 / OPT-022：分模型价目表
# ---------------------------------------------------------------------------
from app.config import settings


class TestModelPrices:
    def test_flat_rate_fallback_for_unknown_model(self, monkeypatch):
        monkeypatch.setattr(settings, "MODEL_PRICES", {})
        cost = compute_cost(_Usage(1000, 1000), "unknown-model")
        assert cost == pytest.approx(2 * _RATE, abs=1e-6)

    def test_per_model_pricing(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "MODEL_PRICES",
            {"m1": {"prompt": 0.001, "completion": 0.003}},
        )
        cost = compute_cost(_Usage(1000, 1000), "m1")
        assert cost == pytest.approx(0.004, abs=1e-9)
        bd = token_breakdown(_Usage(1000, 1000), "m1")
        assert bd["prompt_cost"] == pytest.approx(0.001, abs=1e-9)
        assert bd["completion_cost"] == pytest.approx(0.003, abs=1e-9)
        assert bd["cost"] == pytest.approx(0.004, abs=1e-9)

    def test_missing_side_rate_falls_back_to_flat(self, monkeypatch):
        monkeypatch.setattr(settings, "MODEL_PRICES", {"m2": {"prompt": 0.001}})
        cost = compute_cost(_Usage(1000, 1000), "m2")
        # prompt 按价目表 0.001，completion 回退全局 0.002
        assert cost == pytest.approx(0.003, abs=1e-9)

    def test_models_disaggregation(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "MODEL_PRICES",
            {
                "cheap": {"prompt": 0.0005, "completion": 0.001},
                "pricey": {"prompt": 0.004, "completion": 0.012},
            },
        )
        cheap = compute_cost(_Usage(2000, 2000), "cheap")
        pricey = compute_cost(_Usage(2000, 2000), "pricey")
        assert cheap == pytest.approx(0.003, abs=1e-9)
        assert pricey == pytest.approx(0.032, abs=1e-9)

    def test_env_json_parses_to_dict(self, monkeypatch):
        # pydantic-settings 从 JSON 形式的 env 变量解码 dict（init 传参不 decode，故走 setenv）
        from app.config import Settings

        monkeypatch.setenv("MODEL_PRICES", '{"a": {"prompt": 0.1, "completion": 0.2}}')
        s = Settings(_env_file=None)
        assert s.MODEL_PRICES == {"a": {"prompt": 0.1, "completion": 0.2}}

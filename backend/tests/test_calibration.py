# tests/test_calibration.py —— 质检权重反向校准纯函数单测（J1 质量闭环）
import pytest

from app.calibration import _DEFAULT_ALPHA, fit_weights
from app.engine.quality import _aggregate_score

# 模板默认权重（与 single_choice.yaml 一致）
DEFAULT_WEIGHTS = {
    "kp_match": 0.3,
    "diff_match": 0.2,
    "distractor": 0.3,
    "unambiguous": 0.2,
}

RULES = [
    {"id": "kp_match", "weight": 0.3},
    {"id": "diff_match", "weight": 0.2},
    {"id": "distractor", "weight": 0.3},
    {"id": "unambiguous", "weight": 0.2},
]


class TestFitWeights:
    def test_lenient_dimension_gets_lower_weight(self):
        """放水维度（FP 集高分、Pass 集低分）权重应下降。"""
        # kp_match 在假阳性集给高分（90），但在通过集也给高分（88）→ 几乎无判别力
        # distractor 在假阳性集给高分（85），但通过集给低分（60）→ 明显放水
        fp_dims = [
            {"kp_match": 90, "diff_match": 80, "distractor": 85, "unambiguous": 75},
            {"kp_match": 88, "diff_match": 82, "distractor": 88, "unambiguous": 70},
        ]
        pass_dims = [
            {"kp_match": 88, "diff_match": 75, "distractor": 60, "unambiguous": 80},
            {"kp_match": 90, "diff_match": 78, "distractor": 55, "unambiguous": 85},
        ]

        new_weights, lenient = fit_weights(DEFAULT_WEIGHTS, fp_dims, pass_dims)

        # distractor 放水度应为正且最高
        assert lenient["distractor"] > 0
        assert lenient["distractor"] > lenient["kp_match"]

        # distractor 权重应低于默认
        assert new_weights["distractor"] < DEFAULT_WEIGHTS["distractor"]

        # 权重总和归一化为 1
        total = sum(new_weights.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_no_leniency_keeps_weights(self):
        """无放水维度（所有 lenient ≤ 0）时保持默认权重。"""
        fp_dims = [
            {"kp_match": 60, "diff_match": 50, "distractor": 55, "unambiguous": 45},
        ]
        pass_dims = [
            {"kp_match": 90, "diff_match": 85, "distractor": 88, "unambiguous": 80},
        ]

        new_weights, lenient = fit_weights(DEFAULT_WEIGHTS, fp_dims, pass_dims)

        # 所有放水度 ≤ 0（FP 分比 Pass 分低）
        assert all(v <= 0 for v in lenient.values())
        # 保持默认权重不变
        for k, v in DEFAULT_WEIGHTS.items():
            assert new_weights[k] == v

    def test_empty_fp_returns_default(self):
        """无假阳性样本时返回默认权重。"""
        new_weights, lenient = fit_weights(DEFAULT_WEIGHTS, [], [])
        assert new_weights == DEFAULT_WEIGHTS
        assert lenient == {}

    def test_weight_floor_prevents_zero(self):
        """权重下限钳制防止单维度归零。"""
        # 极端：distractor 在 FP 全给 100，Pass 全给 0 → 最大放水
        fp_dims = [
            {"kp_match": 50, "diff_match": 50, "distractor": 100, "unambiguous": 50},
        ]
        pass_dims = [
            {"kp_match": 50, "diff_match": 50, "distractor": 0, "unambiguous": 50},
        ]

        new_weights, _ = fit_weights(DEFAULT_WEIGHTS, fp_dims, pass_dims, alpha=1.0)

        # distractor 权重应下降但不为 0（被下限钳制）
        assert new_weights["distractor"] > 0
        # 权重总和仍归一化
        assert sum(new_weights.values()) == pytest.approx(1.0, abs=0.01)

    def test_weights_sum_to_one(self):
        """校准后权重总和必须为 1。"""
        fp_dims = [
            {"kp_match": 85, "diff_match": 70, "distractor": 90, "unambiguous": 65},
            {"kp_match": 80, "diff_match": 75, "distractor": 85, "unambiguous": 70},
            {"kp_match": 88, "diff_match": 72, "distractor": 92, "unambiguous": 68},
        ]
        pass_dims = [
            {"kp_match": 78, "diff_match": 80, "distractor": 60, "unambiguous": 85},
            {"kp_match": 82, "diff_match": 78, "distractor": 55, "unambiguous": 88},
        ]

        new_weights, _ = fit_weights(DEFAULT_WEIGHTS, fp_dims, pass_dims)
        assert sum(new_weights.values()) == pytest.approx(1.0, abs=0.02)


class TestAggregateScoreWithOverride:
    def test_override_weights_used(self):
        """提供 weights_override 时应用覆盖权重而非模板默认。"""
        dims = {"kp_match": 80, "diff_match": 90, "distractor": 70, "unambiguous": 60}

        # 默认权重：(80*.3 + 90*.2 + 70*.3 + 60*.2) = 75
        assert _aggregate_score(RULES, dims) == 75.0

        # 覆盖权重：distractor 从 0.3 降到 0.1，kp_match 从 0.3 升到 0.5
        override = {"kp_match": 0.5, "diff_match": 0.2, "distractor": 0.1, "unambiguous": 0.2}
        # (80*.5 + 90*.2 + 70*.1 + 60*.2) / 1.0 = 40+18+7+12 = 77
        result = _aggregate_score(RULES, dims, weights_override=override)
        assert result == pytest.approx(77.0, abs=0.01)

    def test_override_none_falls_back_to_default(self):
        """weights_override=None 时回退到模板默认权重。"""
        dims = {"kp_match": 80, "diff_match": 90, "distractor": 70, "unambiguous": 60}
        assert _aggregate_score(RULES, dims, weights_override=None) == 75.0

    def test_partial_override_merges_with_default(self):
        """覆盖权重只含部分维度时，缺失维度回退默认。"""
        dims = {"kp_match": 80, "diff_match": 90, "distractor": 70, "unambiguous": 60}
        # 只覆盖 kp_match 为 0.6，其余用默认
        override = {"kp_match": 0.6}
        # _aggregate_score 遍历 rules，有 override 用 override，无则用 rule["weight"]
        # kp_match: 0.6, diff_match: 0.2, distractor: 0.3, unambiguous: 0.2
        # 但总权重 = 0.6+0.2+0.3+0.2 = 1.3
        # (80*.6 + 90*.2 + 70*.3 + 60*.2) / 1.3 = (48+18+21+12)/1.3 = 99/1.3 ≈ 76.15
        result = _aggregate_score(RULES, dims, weights_override=override)
        expected = (80 * 0.6 + 90 * 0.2 + 70 * 0.3 + 60 * 0.2) / (0.6 + 0.2 + 0.3 + 0.2)
        assert result == pytest.approx(expected, abs=0.01)

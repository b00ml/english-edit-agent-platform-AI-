# tests/test_agreement.py —— judge 与人工标注一致性纯函数单测（P0-4 / OPT-020）
import pytest

from app.engine.agreement import cohen_kappa, judge_vs_manual


class TestCohenKappa:
    def test_perfect_agreement_is_one(self):
        assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0

    def test_known_example_is_half(self):
        # 经典手算例：po=0.75, pe=0.5 -> kappa=0.5
        assert cohen_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == 0.5

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            cohen_kappa([1, 0], [1])

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            cohen_kappa([], [])

    def test_degenerate_distribution_returns_one(self):
        # 边缘分布退化（pe>=1）时约定返回 1.0
        assert cohen_kappa([0, 0], [0, 0]) == 1.0


class TestJudgeVsManual:
    def test_known_confusion_and_metrics(self):
        # threshold=70：TP/TN/FP/FN 各 1
        pairs = [(80.0, 1.0), (60.0, 0.0), (80.0, 0.0), (60.0, 1.0)]
        r = judge_vs_manual(pairs, 70.0)
        assert (r["tp"], r["tn"], r["fp"], r["fn"]) == (1, 1, 1, 1)
        assert r["n"] == 4
        assert r["accuracy"] == 0.5
        assert r["precision"] == 0.5
        assert r["recall"] == 0.5
        assert r["f1"] == 0.5
        # y_true=[1,0,0,1], y_pred=[1,0,1,0] -> po=0.5, pe=0.5 -> kappa=0.0
        # （准确率 0.5 恰等于随机一致水平，kappa 为 0 才是正确口径）
        assert r["kappa"] == 0.0

    def test_empty_pairs_return_none_metrics(self):
        r = judge_vs_manual([], 70.0)
        assert r["n"] == 0
        assert r["accuracy"] is None and r["kappa"] is None

    def test_no_positive_predictions_precision_none(self):
        # 人工全驳回且 judge 分都低于阈值：无预测正例，precision 为 None
        pairs = [(50.0, 0.0), (60.0, 0.0)]
        r = judge_vs_manual(pairs, 70.0)
        assert r["tp"] == 0 and r["fp"] == 0
        assert r["precision"] is None
        assert r["accuracy"] == 1.0
        assert r["kappa"] == 1.0

    def test_false_positive_semantics(self):
        # FP = auto 高分（judge 通过）但人工驳回 —— 正是反向校准的假阳性集
        r = judge_vs_manual([(85.0, 0.0)], 70.0)
        assert r["fp"] == 1 and r["tn"] == 0 and r["tp"] == 0 and r["fn"] == 0

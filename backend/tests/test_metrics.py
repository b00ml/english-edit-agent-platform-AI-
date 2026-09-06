# tests/test_metrics.py —— 结构化符合率统计纯函数单测（P0-2 / OPT-016）
import pytest

from app.engine.metrics import compute_structured_stats


def _row(tid, attempt, success):
    return {"trace_id": tid, "attempt": attempt, "success": success}


class TestComputeStructuredStats:
    def test_empty_returns_none_rates(self):
        stats = compute_structured_stats([])
        assert stats["total_generations"] == 0
        assert stats["success_generations"] == 0
        assert stats["failed_generations"] == 0
        assert stats["first_pass_rate"] is None
        assert stats["avg_attempts"] is None
        assert stats["failure_rate"] is None

    def test_all_first_pass(self):
        stats = compute_structured_stats([_row("a", 1, True), _row("b", 1, True)])
        assert stats["total_generations"] == 2
        assert stats["success_generations"] == 2
        assert stats["failed_generations"] == 0
        assert stats["first_pass_rate"] == 1.0
        assert stats["avg_attempts"] == 1.0
        assert stats["failure_rate"] == 0.0

    def test_mixed_threads(self):
        # a 一次成功；b 重试 3 次成功；c 两次尝试全失败
        rows = [
            _row("a", 1, True),
            _row("b", 1, False),
            _row("b", 2, False),
            _row("b", 3, True),
            _row("c", 1, False),
            _row("c", 2, False),
        ]
        stats = compute_structured_stats(rows)
        assert stats["total_generations"] == 3
        assert stats["success_generations"] == 2
        assert stats["failed_generations"] == 1
        assert stats["first_pass_rate"] == 0.5
        assert stats["avg_attempts"] == 2.0
        assert stats["failure_rate"] == pytest.approx(0.3333, abs=1e-4)

    def test_duplicate_success_rows_dedup_min_attempt(self):
        # 防御：同一 thread 理论仅一条成功行，重复时取最小 attempt
        stats = compute_structured_stats([_row("a", 2, True), _row("a", 1, True)])
        assert stats["success_generations"] == 1
        assert stats["avg_attempts"] == 1.0

    def test_all_failed(self):
        stats = compute_structured_stats([_row("a", 1, False), _row("a", 2, False)])
        assert stats["success_generations"] == 0
        assert stats["first_pass_rate"] is None
        assert stats["avg_attempts"] is None
        assert stats["failure_rate"] == 1.0

    def test_null_attempt_treated_as_first(self):
        # 历史/异常数据 attempt 为空时按 1 解释
        stats = compute_structured_stats([{"trace_id": "a", "attempt": None, "success": True}])
        assert stats["first_pass_rate"] == 1.0

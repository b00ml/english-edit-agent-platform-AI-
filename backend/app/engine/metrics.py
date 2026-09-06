# app/engine/metrics.py —— 结构化输出符合率统计（P0-2 / OPT-016）
# 指标口径见 docs/优化技术设计2.0.md §7 指标字典：
#   - 首过率 first_pass_rate：一次尝试即通过校验的成功生成 / 全部成功生成
#   - 平均尝试次数 avg_attempts：成功生成的 attempt 均值
#   - 最终失败率 failure_rate：无成功调用行的生成 thread（trace_id）占比
# 纯函数，便于单测与多处复用（dashboard KPI 与 /api/traces/structured-stats）。
from typing import Any, Dict, Iterable


def compute_structured_stats(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """由 generate 阶段的 TraceLog 行计算结构化符合率指标（纯函数）。

    rows 每行需含：
      - trace_id：生成 thread 标识（一次生成的多次尝试共享同一 trace_id）；
      - attempt：本次调用为第几次尝试（1 起）；
      - success：该次调用是否通过 Pydantic 校验。
    stage 过滤由调用方完成（仅传 stage='generate' 的行）。

    返回 {total_generations, success_generations, failed_generations,
          first_pass_rate, avg_attempts, failure_rate}；
    无样本或无成功样本时对应比率为 None（区别于 0，供展示层决定显示方式）。
    """
    threads: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        tid = row["trace_id"]
        thread = threads.setdefault(tid, {"success_attempt": None})
        if row.get("success"):
            attempt = int(row.get("attempt") or 1)
            # 防御：同一 thread 理论上只有一条成功行，取最小 attempt 兜底
            if thread["success_attempt"] is None or attempt < thread["success_attempt"]:
                thread["success_attempt"] = attempt

    total = len(threads)
    success_attempts = [
        t["success_attempt"] for t in threads.values() if t["success_attempt"] is not None
    ]
    failed = total - len(success_attempts)

    return {
        "total_generations": total,
        "success_generations": len(success_attempts),
        "failed_generations": failed,
        "first_pass_rate": (
            round(sum(1 for a in success_attempts if a == 1) / len(success_attempts), 4)
            if success_attempts
            else None
        ),
        "avg_attempts": (
            round(sum(success_attempts) / len(success_attempts), 4) if success_attempts else None
        ),
        "failure_rate": round(failed / total, 4) if total else None,
    }

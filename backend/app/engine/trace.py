# app/engine/trace.py —— LLM 调用可观测性与成本记录
# 每次 LLM 调用组装一条 trace dict，按 settings.TRACE_SINKS 分发到各 Sink：
#   - db：自研 TraceLog 表（SSOT，trace_id/model/cost/latency/attempt/success 入库），
#     供成本聚合接口（/api/costs）与链路回放使用；
#   - langfuse：可选导出通道（见 observability.LangfuseSink）。
# 任一 Sink 写入失败仅告警，不影响其余 Sink 与业务主流程。
import logging
import time
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger("app.engine.trace")

# Sink 单例缓存（按 sink 名），reset_sinks() 供配置变更与测试后重建
_SINKS: Dict[str, Any] = {}


def reset_sinks() -> None:
    """清空 Sink 缓存，下次 record_trace 按最新配置重建。"""
    _SINKS.clear()


def _build_sinks() -> None:
    """按 TRACE_SINKS 配置实例化 Sink（db / langfuse）。"""
    from app.engine.observability import LangfuseSink, TraceLogSink

    for name in (s.strip() for s in settings.TRACE_SINKS.split(",") if s.strip()):
        if name in _SINKS:
            continue
        if name == "db":
            _SINKS[name] = TraceLogSink()
        elif name == "langfuse":
            _SINKS[name] = LangfuseSink()
        else:
            logger.warning("未知 trace sink 配置项: %s（已跳过）", name)


def _get_sinks() -> List[Any]:
    if not _SINKS:
        _build_sinks()
    return list(_SINKS.values())


def _model_rates(model: str) -> tuple[float, float]:
    """解析模型单价（每 1K token）：命中 MODEL_PRICES 用分模型价，未命中回退全局单一单价。

    价目表形如 {"模型名": {"prompt": x, "completion": y}}；缺某侧单价时该侧回退全局价。
    """
    price = (settings.MODEL_PRICES or {}).get(model)
    if price:
        flat = settings.COST_PER_1K_TOKENS
        return float(price.get("prompt", flat)), float(price.get("completion", flat))
    rate = settings.COST_PER_1K_TOKENS
    return rate, rate


def compute_cost(usage: Optional[Any], model: str) -> float:
    """按 token 用量估算成本：优先分模型价目表（P1-3），未命中回退全局单价。"""
    prompt, completion = _token_usage(usage)
    p_rate, c_rate = _model_rates(model)
    return round(prompt / 1000.0 * p_rate + completion / 1000.0 * c_rate, 6)


def token_breakdown(usage: Optional[Any], model: str) -> Dict[str, Any]:
    """将 token 用量细分为输入/输出 token 数与各自成本（分模型计价）。

    供深度成本报表（K2）按生成/质检阶段拆分 token 与成本。
    返回 {prompt_tokens, completion_tokens, prompt_cost, completion_cost, cost}。
    """
    prompt, completion = _token_usage(usage)
    p_rate, c_rate = _model_rates(model)
    prompt_cost = round(prompt / 1000.0 * p_rate, 6)
    completion_cost = round(completion / 1000.0 * c_rate, 6)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "prompt_cost": prompt_cost,
        "completion_cost": completion_cost,
        "cost": round(prompt_cost + completion_cost, 6),
    }


def _token_usage(usage: Optional[Any]) -> tuple[int, int]:
    """提取 usage 中的输入/输出 token 数（缺失按 0 计）。"""
    if usage is None:
        return 0, 0
    prompt = getattr(usage, "prompt_tokens", None) or 0
    completion = getattr(usage, "completion_tokens", None) or 0
    return int(prompt), int(completion)


def record_trace(
    *,
    trace_id: str,
    model: str,
    latency_ms: float,
    cost: float,
    prompt_version: str = "",
    task_id: Optional[str] = None,
    template_id: Optional[str] = None,
    item_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    input_data: Optional[Dict[str, Any]] = None,
    output_data: Optional[Dict[str, Any]] = None,
    stage: str = "",
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    attempt: int = 1,
    success: bool = True,
) -> None:
    """组装一条 trace 并分发到所有配置的 Sink（失败尝试同样记录）。

    attempt/success 用于结构化符合率统计（P0-2）：generate 阶段每次调用
    （含校验失败的尝试）各写一行，失败行 output_data 为 {"error_summary": ...}。
    单个 Sink 失败仅告警，不中断其余 Sink 与生成主流程。
    """
    trace: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "template_id": template_id,
        "item_id": item_id,
        "prompt_version": prompt_version,
        "model": model,
        "input_data": input_data,
        "output_data": output_data,
        "latency_ms": latency_ms,
        "cost": cost,
        "stage": stage,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tenant_id": tenant_id,
        "attempt": attempt,
        "success": success,
    }
    for sink in _get_sinks():
        try:
            sink.emit(trace)
        except Exception:  # noqa: BLE001 —— 可观测性写入失败不应中断生成主流程
            logger.warning("trace sink 写入失败 sink=%s", type(sink).__name__, exc_info=True)


def elapsed_ms(start_ns: int) -> float:
    """从单调时钟起点计算耗时（毫秒）。"""
    return round((time.perf_counter_ns() - start_ns) / 1_000_000, 2)

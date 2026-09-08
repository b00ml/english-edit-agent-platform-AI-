# app/engine/quality.py —— LLM-as-judge 自动质检
# 按模板 quality_rules 逐维度打分（0-100），加权汇总；judge 多次采样取均值以降低抖动。
import json
import logging
import time
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from app.config import settings
from app.engine.trace import compute_cost, elapsed_ms, record_trace, token_breakdown
from app.errors import QualityCheckError
from app.prompt_loader import load_prompt, render
from app.skill_registry import get_skill_by_id

logger = logging.getLogger("app.engine.quality")

# judge 采样的默认轮数（降低抖动）
_JUDGE_ROUNDS = settings.JUDGE_SAMPLE_ROUNDS


def resolve_judge_model(template: Any) -> str:
    """解析 judge 模型（P1-2 自偏好治理）：模板 run_config.judge_model > 全局
    JUDGE_MODEL_NAME > LLM_MODEL_NAME。建议 judge 与生成主模型不同家族。
    """
    run_config = getattr(template, "run_config", None) or {}
    return run_config.get("judge_model") or settings.JUDGE_MODEL_NAME or settings.LLM_MODEL_NAME


def _aggregate_score(
    rules: List[Dict[str, Any]],
    dimension_scores: Dict[str, float],
    weights_override: Optional[Dict[str, float]] = None,
) -> float:
    """按 quality_rules 权重对维度分加权汇总（0-100）。

    若提供 weights_override，则用覆盖权重替代模板默认权重（J1 校准生效点）。
    缺失维度的权重映射到剩余维度（归一化）；无可用权重时取维度平均分兜底。
    """
    total_weight = 0.0
    weighted_sum = 0.0
    for rule in rules:
        rid = rule.get("id")
        if weights_override and rid in weights_override:
            weight = weights_override[rid]
        else:
            weight = float(rule.get("weight", 0.0))
        if rid in dimension_scores:
            weighted_sum += dimension_scores[rid] * weight
            total_weight += weight

    if total_weight <= 0:
        # 兜底：无可用权重时取各维度平均分
        return mean(dimension_scores.values())
    return weighted_sum / total_weight


def aggregate_rounds(round_scores: List[Dict[str, float]]) -> Dict[str, float]:
    """将多轮 judge 采样按维度取均值，降低单次抽样的抖动。

    对每个维度收集所有轮次的得分并求算术平均；某维度的缺失轮视为无该轮得分。
    均值聚合使同一样本的质检分趋于稳定（方差按轮数 n 下降为单次的 1/n）。
    """
    accumulated: Dict[str, List[float]] = {}
    for once in round_scores:
        for rid, score in once.items():
            accumulated.setdefault(rid, []).append(score)
    return {rid: mean(scores) for rid, scores in accumulated.items()}


def _get_openai_client() -> OpenAI:
    """构建 OpenAI 兼容客户端（可测试缝：单测/集成测试可整体替换本函数）。"""
    return OpenAI(
        base_url=settings.LLM_API_BASE,
        api_key=settings.LLM_API_KEY or "sk-placeholder",
        timeout=settings.LLM_TIMEOUT,
    )


def _build_judge_prompt(template: Any, payload: Dict[str, Any]) -> Tuple[str, str]:
    """构造 judge 的系统与用户提示。

    - system/user prompt 从独立 .st 文件加载（prompts/judge-*.st），符合
      Prompt 工程化规范，可独立版本化与调试；
    - 注入 judge 质检技能规范（skills/judge/SKILL.md）作为打分行为约束；
    - 将模板 quality_rules 的维度描述与分档评分标准（rubric）结构化注入
      user prompt，让 judge 依据统一、明确的评分尺度打分，降低尺度漂移；
    - 兼容旧模板：仅含 id/weight 时退化为简单打分说明。
    """
    rules = template.quality_rules or []
    rubric_lines = []
    for r in rules:
        rid = r.get("id", "")
        weight = r.get("weight", 0.0)
        desc = r.get("description", "")
        rubric = r.get("rubric") or {}
        base = f"- {rid}（权重 {weight}）"
        if desc:
            base += f"：{desc}"
        rubric_lines.append(base)
        if isinstance(rubric, dict):
            for band, std in rubric.items():
                rubric_lines.append(f"    {band} 分：{std}")

    # 从独立 .st 文件加载 system prompt，并注入 judge 质检技能规范
    system_prompt = load_prompt("judge-system.st")
    skill_md = get_skill_by_id("judge")
    if skill_md:
        system_prompt = f"{system_prompt}\n\n# 质检技能规范\n{skill_md}"

    # 渲染 user prompt：注入 rubric 文本与待质检 payload
    user_prompt = render(
        load_prompt("judge-user.st"),
        {
            "rubric": "\n".join(rubric_lines),
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )
    return system_prompt, user_prompt


def _call_judge_once(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    rule_ids: List[str],
) -> Tuple[Dict[str, float], float, Any]:
    """调用 judge 一次，返回 (各规则维度得分, 耗时毫秒, token usage)。"""
    start = time.perf_counter_ns()
    resp = client.chat.completions.create(
        model=model,
        temperature=settings.JUDGE_TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    data = json.loads(content)
    dims = data.get("dimension_scores", {}) or {}
    # 仅保留模型返回的、且属于规则声明的维度，并强制为数值
    result = {
        rid: float(dims.get(rid, 0.0))
        for rid in rule_ids
        if rid in dims and isinstance(dims.get(rid), (int, float))
    }
    return result, elapsed_ms(start), resp.usage


def run_quality_check(
    template: Any,
    payload: Dict[str, Any],
    model_name: str = "",
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    template_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    rounds: Optional[int] = None,
    weights_override: Optional[Dict[str, float]] = None,
) -> Tuple[float, Dict[str, Any]]:
    """执行自动质检，返回 (总分 0-100, 维度分 dict)。

    - 按 quality_rules 逐维度打 0-100 分；
    - 多次采样（默认取配置 JUDGE_SAMPLE_ROUNDS，或显式 rounds）取各维度均值，降低抖动；
    - 按权重加权汇总得到总分（若提供 weights_override 则用校准权重）；
    - judge 模型：显式传入优先；否则 JUDGE_MODEL_NAME / LLM_MODEL_NAME 兜底（P1-2）；
    - 每次 judge 采样记录 TraceLog（耗时/成本）与结构化日志。
    """
    if not model_name:
        model_name = settings.JUDGE_MODEL_NAME or settings.LLM_MODEL_NAME
    rules = template.quality_rules or []
    rule_ids = [r.get("id") for r in rules if isinstance(r, dict)]

    client = _get_openai_client()
    system_prompt, user_prompt = _build_judge_prompt(template, payload)

    judge_rounds = rounds if rounds is not None else _JUDGE_ROUNDS
    # 收集各轮采样结果
    round_scores: List[Dict[str, float]] = []
    for round_idx in range(judge_rounds):
        try:
            once, latency_ms, usage = _call_judge_once(
                client, model_name, system_prompt, user_prompt, rule_ids
            )
            cost = compute_cost(usage, model_name)
            tokens = token_breakdown(usage, model_name)
            if trace_id:
                record_trace(
                    trace_id=trace_id,
                    task_id=task_id,
                    template_id=template_id,
                    model=model_name,
                    latency_ms=latency_ms,
                    cost=cost,
                    prompt_version=template.version,
                    tenant_id=tenant_id,
                    input_data={"payload": payload},
                    output_data={"dimension_scores": once},
                    stage="qc",
                    prompt_tokens=tokens["prompt_tokens"],
                    completion_tokens=tokens["completion_tokens"],
                )
            logger.info(
                "质检采样 trace_id=%s model=%s round=%d latency_ms=%.1f cost=%.6f dims=%s",
                trace_id,
                model_name,
                round_idx + 1,
                latency_ms,
                cost,
                once,
            )
            if once:  # 跳过空维度返回，避免聚合出空表导致后续崩溃
                round_scores.append(once)
        except (json.JSONDecodeError, KeyError, ValueError):
            # 单次采样失败则跳过该轮，避免整体失败
            continue

    if not round_scores:
        raise QualityCheckError("自动质检失败：judge 所有采样均未返回有效维度分")

    # 多轮均值聚合（降低抖动）
    dimension_scores = aggregate_rounds(round_scores)
    if not dimension_scores:
        raise QualityCheckError("自动质检失败：judge 未返回任何有效维度分")

    # 加权汇总（缺失维度权重归一化，无权重时取平均分兜底）
    score = _aggregate_score(rules, dimension_scores, weights_override)

    return round(score, 2), dimension_scores

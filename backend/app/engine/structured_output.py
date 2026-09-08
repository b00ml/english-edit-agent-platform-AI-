# app/engine/structured_output.py —— 结构化内容生成
# 负责：由 output_schema 构造 Pydantic 模型 -> 调用 OpenAI 兼容云 API 强制输出 JSON
#       -> Pydantic 二次校验 -> 校验错误回注重试（max_retry）-> 耗尽抛异常。
# 重试采用多轮消息：将上次原始输出与字段级错误摘要回注给模型（对齐 Instructor
# 的 reask 模式），使重试带修正目标而非原样重发；可用 STRUCTURED_RETRY_FEEDBACK 关闭。
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Type

import jsonschema
from openai import OpenAI
from pydantic import BaseModel, ValidationError, create_model

from app.config import settings
from app.engine.trace import compute_cost, elapsed_ms, record_trace, token_breakdown
from app.errors import StructuredOutputError
from app.prompt_loader import build_system_prompt, build_user_prompt, load_prompt, render
from app.skill_registry import get_skill_md

logger = logging.getLogger("app.engine.structured_output")

# ---------------------------------------------------------------------------
# 关于 Outlines 约束解码的说明（本实现以 OpenAI 客户端 + 强制 JSON 实现）
# ---------------------------------------------------------------------------
# Outlines 的约束解码（structured generation）思想是：在采样阶段用正则/FSM 约束
# 输出 token，保证模型输出“必然”符合给定结构。原生集成需要：
#   1. 用 outlines.generate.json(model, pydantic_model) 生成采样器；
#   2. 把 sampler 绑定到与 OpenAI 兼容的本地推理服务（如 vLLM / llama.cpp）；
#   3. 对纯云端托管 API（如 api.openai.com），无法直接注入约束解码器。
# 因此本模块采用等效方案：构造 Pydantic 模型约束结构 -> 提示词强制 JSON ->
# 调用 OpenAI 客户端 -> 用 Pydantic 二次校验（保证结构合法，效果等同约束解码）。
# 若后续接入本地 vLLM 推理端点，可无缝替换为 outlines.generate.json 采样器。


def _build_pydantic_from_schema(schema: Dict[str, Any]) -> Type[BaseModel]:
    """从 output_schema（JSON Schema）动态构造 Pydantic 模型。

    目前覆盖 object 与 array 两种顶层类型；复杂嵌套字段先映射为 Any，
    结构合法性由 LLM 输出 + 二次校验兜底。
    """
    if schema.get("type") != "object":
        # 顶层为数组时，用一个包裹模型承接
        return create_model("OutputModel", items=(List[Any], ...))

    fields: Dict[str, Any] = {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []) or [])
    for name, prop in properties.items():
        field_type = _map_schema_type(prop)
        if name in required:
            fields[name] = (field_type, ...)
        else:
            fields[name] = (field_type, None)
    return create_model("OutputModel", **fields)


def _map_schema_type(prop: Dict[str, Any]) -> object:
    """将 JSON Schema 类型映射为 Python 类型标注（保留约束：enum/minLength/maxLength/minItems/maxItems）。"""
    from typing import Literal

    from pydantic import conlist, constr

    ptype = prop.get("type")

    if ptype == "string":
        # 枚举值用 Literal 约束
        enum = prop.get("enum")
        if enum:
            return Literal[tuple(enum)]  # type: ignore[valid-type]
        # 字符串长度约束
        min_len = prop.get("minLength")
        max_len = prop.get("maxLength")
        if min_len is not None or max_len is not None:
            return constr(min_length=min_len, max_length=max_len)  # type: ignore[valid-type]
        return str

    if ptype == "integer":
        return int

    if ptype == "number":
        return float

    if ptype == "boolean":
        return bool

    if ptype == "array":
        items = prop.get("items")
        min_items = prop.get("minItems")
        max_items = prop.get("maxItems")

        # 数组元素为对象时递归构造内部模型
        if isinstance(items, dict) and items.get("type") == "object":
            inner = _build_pydantic_from_schema(items)
            # 保留数组长度约束
            if min_items is not None or max_items is not None:
                return conlist(  # type: ignore[valid-type]
                    inner, min_length=min_items, max_length=max_items
                )
            return List[inner]  # type: ignore[name-defined]

        # 普通数组保留长度约束
        if min_items is not None or max_items is not None:
            return conlist(  # type: ignore[valid-type]
                Any, min_length=min_items, max_length=max_items
            )
        return List[Any]

    if ptype == "object":
        # 对象递归构造内部模型
        return _build_pydantic_from_schema(prop)

    return Any


def _build_schema_instruction(schema: Dict[str, Any], indent: str = "") -> str:
    """把 output_schema 渲染成给模型的 JSON 结构说明（支持嵌套对象与数组）。

    顶层必须是对象；对 array/object 字段递归展开其元素结构，明确字段名、类型、
    枚举取值与必填属性，避免模型输出嵌套包装或字段缺失。
    外层包装文本从独立 `schema-constraint.st` 加载，符合 Prompt 工程化规范。
    """
    if schema.get("type") != "object":
        return ""
    props = schema.get("properties", {})
    required = set(schema.get("required", []) or [])
    lines = []
    for name, prop in props.items():
        ptype = prop.get("type", "any")
        enum = prop.get("enum")
        req = "必填" if name in required else "可选"
        desc = f"{indent}- 字段 {name}: 类型 {ptype}"
        if enum:
            desc += f"，取值只能是其中之一: {enum}"
        desc += f"（{req}）"
        lines.append(desc)
        # 数组：递归展开其元素结构
        if ptype == "array":
            items = prop.get("items", {})
            lines.append(f"{indent}  数组元素结构：")
            lines.append(_schema_fields(items, indent + "    ") or f"{indent}    - 任意元素")
        # 对象：递归展开其子字段
        elif ptype == "object":
            lines.append(f"{indent}  子对象字段：")
            lines.append(_schema_fields(prop, indent + "    ") or f"{indent}    - 任意字段")
    if indent:
        return "\n".join(lines)
    return render(
        load_prompt("schema-constraint.st"),
        {"schema_fields": "\n".join(lines)},
    )


def _schema_fields(schema: Dict[str, Any], indent: str = "") -> str:
    """递归渲染对象/数组元素的字段说明（供 _build_schema_instruction 复用）。"""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return ""
    props = schema.get("properties", {})
    required = set(schema.get("required", []) or [])
    lines = []
    for name, prop in props.items():
        ptype = prop.get("type", "any")
        enum = prop.get("enum")
        req = "必填" if name in required else "可选"
        desc = f"{indent}- 字段 {name}: 类型 {ptype}"
        if enum:
            desc += f"，取值只能是其中之一: {enum}"
        desc += f"（{req}）"
        lines.append(desc)
        if ptype == "array":
            lines.append(f"{indent}  数组元素结构：")
            lines.append(
                _schema_fields(prop.get("items", {}), indent + "    ") or f"{indent}    - 任意元素"
            )
        elif ptype == "object":
            lines.append(f"{indent}  子对象字段：")
            lines.append(_schema_fields(prop, indent + "    ") or f"{indent}    - 任意字段")
    return "\n".join(lines)


def _normalize_flat(schema: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """针对模型偶发嵌套包装做兜底展平。

    当顶层缺少全部必填字段、但恰好包含一个子对象且该子对象具备所有必填字段时，
    直接使用该子对象作为结果。否则原样返回（交由 Pydantic 二次校验判错）。
    """
    # 模型偶发返回 JSON 数组等非对象结构时，原样返回交由 Pydantic 校验判错并触发重试，
    # 避免对 list 调用 .keys() 抛 AttributeError 逃逸出重试逻辑。
    if not isinstance(data, dict):
        return data
    required = set(schema.get("required", []) or [])
    if required and not required.issubset(data.keys()):
        for key, value in data.items():
            if isinstance(value, dict) and required.issubset(value.keys()):
                return value
            # 数组包装：模型偶发返回 {"questions":[{...}]} 或 {"items":[...]}，
            # 取首个满足全部必填字段的子对象，避免无谓重试导致的失败/耗时。
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and required.issubset(item.keys()):
                        return item
    return data


def _get_openai_client() -> OpenAI:
    """构建 OpenAI 兼容客户端（可测试缝：单测/集成测试可整体替换本函数）。"""
    return OpenAI(
        base_url=settings.LLM_API_BASE,
        api_key=settings.LLM_API_KEY or "sk-placeholder",
        timeout=settings.LLM_TIMEOUT,
    )


def _summarize_validation_error(exc: Exception) -> str:
    """把校验/解析异常压缩为人类可读的字段级错误摘要，供重试回注与 TraceLog 记录。

    - ValidationError：逐条输出字段路径/错误类型/信息/输入（截断），最多列 10 条；
    - JSONDecodeError / KeyError：输出对应说明；
    """
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        lines = []
        for err in errors[:10]:
            loc = ".".join(str(p) for p in err.get("loc", ()))
            inp = repr(err.get("input"))
            if len(inp) > 80:
                inp = inp[:77] + "..."
            lines.append(
                f"- 字段 {loc or '<顶层>'} [{err.get('type', '')}]: "
                f"{err.get('msg', '')}；输入: {inp}"
            )
        extra = len(errors) - 10
        if extra > 0:
            lines.append(f"- ……另有 {extra} 条错误未列出")
        return "\n".join(lines)
    if isinstance(exc, json.JSONDecodeError):
        return f"输出不是合法 JSON：{exc}（请检查引号、逗号与括号是否配对）"
    if isinstance(exc, KeyError):
        return f"输出缺少预期字段：{exc}"
    return f"校验失败：{exc}"


def _call_openai_json(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, str]],
) -> Tuple[str, float, Any]:
    """调用 OpenAI 兼容 API，返回 (原始文本, 耗时毫秒, token usage)。

    不在此处做 JSON 解析：解析失败时调用方仍能拿到本次调用的 usage 与耗时，
    保证失败尝试也可完整记入 TraceLog（成本口径含重试）。
    """
    start = time.perf_counter_ns()
    resp = client.chat.completions.create(
        model=model,
        temperature=settings.LLM_TEMPERATURE,
        response_format={"type": "json_object"},
        messages=messages,
    )
    content = resp.choices[0].message.content or "{}"
    return content, elapsed_ms(start), resp.usage


def generate_structured(
    template: Any,
    params: Dict[str, Any],
    model_profile: Any,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    template_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """根据模板生成符合 output_schema 的单条结构化内容。

    - 从 output_schema 构造 Pydantic 模型；
    - 调用 OpenAI 兼容云 API（base_url / key 取自全局配置）；
    - 对返回结果做 Pydantic 二次校验；
    - 校验失败按 run_config.max_retry 重试（默认 3），重试时回注上次输出与
      字段级错误摘要（STRUCTURED_RETRY_FEEDBACK 控制），耗尽抛异常；
    - 每次调用（含失败尝试）记录 TraceLog（耗时/成本/attempt/success）与结构化日志。
    """
    run_config = template.run_config or {}
    max_retry = int(run_config.get("max_retry", 3))

    model_name = (model_profile.model_name if model_profile else None) or settings.LLM_MODEL_NAME
    client = _get_openai_client()

    schema = template.output_schema
    output_model = _build_pydantic_from_schema(schema)
    schema_instruction = _build_schema_instruction(schema)
    # 出题技能规范：按题型经 skill 注册表加载，注入 system prompt 作为出题约束
    skill_md = get_skill_md(template.type_id)
    system_prompt = build_system_prompt(template, params, skill_md=skill_md)
    if schema_instruction:
        # 把结构约束并入 system 提示，降低模型返回嵌套/字段缺失的概率
        system_prompt = f"{system_prompt}\n\n{schema_instruction}"
    user_prompt = build_user_prompt(template, params)
    # 改版指令（由 workflow.revise 节点准备，携带上一稿与质检反馈）并入 user prompt
    revise_instruction = params.get("revise_instruction")
    if revise_instruction:
        user_prompt = f"{user_prompt}\n\n{revise_instruction}"

    # 多轮消息列表：重试时回注上次输出与错误摘要（STRUCTURED_RETRY_FEEDBACK 控制）
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": render(load_prompt("json-enforce.st"), {"user_prompt": user_prompt}),
        },
    ]

    last_error: Exception | None = None
    attempt_summaries: List[str] = []
    for attempt in range(1, max_retry + 1):
        try:
            text, latency_ms, usage = _call_openai_json(client, model_name, messages)
            raw = json.loads(text)
            # 兜底展平偶发嵌套包装后再做 Pydantic 二次校验
            validated = output_model.model_validate(_normalize_flat(schema, raw))
            # 第二道校验：用 jsonschema 兜底无法转为 Pydantic 的约束
            validated_dict = validated.model_dump()
            try:
                jsonschema.validate(validated_dict, schema)
            except jsonschema.ValidationError as json_exc:
                # jsonschema 校验失败，触发重试
                raise json_exc
        except (ValidationError, json.JSONDecodeError, KeyError) as exc:
            summary = _summarize_validation_error(exc)
            attempt_summaries.append(f"第{attempt}次: {summary}")
            last_error = exc
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
                    input_data={"params": params},
                    output_data={"error_summary": summary},
                    stage="generate",
                    prompt_tokens=tokens["prompt_tokens"],
                    completion_tokens=tokens["completion_tokens"],
                    attempt=attempt,
                    success=False,
                )
            logger.info(
                "生成校验失败 trace_id=%s model=%s attempt=%d latency_ms=%.1f cost=%.6f summary=%s",
                trace_id,
                model_name,
                attempt,
                latency_ms,
                cost,
                summary.replace("\n", " | "),
            )
            if attempt >= max_retry:
                break
            if settings.STRUCTURED_RETRY_FEEDBACK:
                if isinstance(exc, ValidationError):
                    # 回注上次原始输出（已解析的结构），供模型对照修正；
                    # JSONDecodeError 路径无可用结构化输出，仅回注错误说明
                    messages.append(
                        {
                            "role": "assistant",
                            "content": json.dumps(raw, ensure_ascii=False)[:2000],
                        }
                    )
                messages.append(
                    {
                        "role": "user",
                        "content": render(
                            load_prompt("retry-feedback.st"), {"error_summary": summary}
                        ),
                    }
                )
            continue

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
                input_data={"params": params},
                output_data=validated.model_dump(),
                stage="generate",
                prompt_tokens=tokens["prompt_tokens"],
                completion_tokens=tokens["completion_tokens"],
                attempt=attempt,
                success=True,
            )
        logger.info(
            "生成成功 trace_id=%s model=%s attempt=%d latency_ms=%.1f cost=%.6f",
            trace_id,
            model_name,
            attempt,
            latency_ms,
            cost,
        )
        return validated.model_dump()

    raise StructuredOutputError(
        f"结构化生成失败：经过 {max_retry} 次重试仍未通过 Pydantic 校验。"
        f"各次错误: {'; '.join(attempt_summaries)}；最后一次错误: {last_error}"
    )

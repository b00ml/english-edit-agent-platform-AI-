# app/engine/router.py —— 模型路由与降级
# 按 run_config.model_profile 路由到主模型；主模型失败时降级到备用/默认模型。
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.structured_output import generate_structured
from app.errors import ModelRoutingError
from app.models import ModelProfile


def resolve_model_profile(session: Session, profile_name: Optional[str]) -> Optional[ModelProfile]:
    """按 profile_name 解析模型档案，找不到时降级到 is_default 的默认档案。

    - 优先精确匹配 profile_name；
    - 未匹配则返回 is_default=True 的记录；
    - 均无则返回 None（由调用方决定使用内置默认模型名）。
    """
    if profile_name:
        profile = session.execute(
            select(ModelProfile).where(ModelProfile.name == profile_name)
        ).scalar_one_or_none()
        if profile:
            return profile

    # 降级到默认档案
    default = session.execute(
        select(ModelProfile).where(ModelProfile.is_default.is_(True))
    ).scalar_one_or_none()
    return default


def _resolve_primary_profile_name(
    run_config: dict,
    params: dict,
    profile_name: Optional[str] = None,
) -> Optional[str]:
    """解析本次生成的主模型档案名。

    `run_config.model_profile` 支持两种形态（配置驱动，新增分档不改代码）：

    - 字符串（历史兼容）：直接作为档案名；
    - 字典（按难度分档）：按 `params.difficulty` 选对应档位，
      缺档优先回退 `default` 键，再回退到任意一个档位值。

    显式传入的 `profile_name` 优先于 run_config。
    """
    effective = profile_name if profile_name is not None else run_config.get("model_profile")
    if isinstance(effective, str):
        return effective
    if isinstance(effective, dict):
        difficulty = params.get("difficulty")
        if difficulty is not None and difficulty in effective:
            return effective[difficulty]
        if "default" in effective:
            return effective["default"]
        if effective:
            return next(iter(effective.values()))
    return None


def generate_with_fallback(
    template: Any,
    params: dict,
    session: Session,
    profile_name: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    template_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> dict:
    """主模型失败后降级到备用/默认模型的生成入口。

    路由顺序：按 run_config.model_profile（含难度分档）解析出的主模型
      -> 降级到 is_default 默认模型 -> 使用内置默认模型名（settings.LLM_MODEL_NAME）。
    任一成功即返回；全部失败抛异常。
    """
    run_config = template.run_config or {}
    primary_name = _resolve_primary_profile_name(run_config, params, profile_name)

    # 候选模型档案列表（主 -> 默认）
    candidates: list[Optional[ModelProfile]] = []
    primary = resolve_model_profile(session, primary_name)
    candidates.append(primary)

    default = resolve_model_profile(session, None)
    if default is not None and default.id != (primary.id if primary else None):
        candidates.append(default)

    # 去重（避免主/默认相同导致重复尝试同一次降级）
    seen: set = set()
    last_error: Optional[Exception] = None
    for candidate in candidates:
        if candidate is None:
            continue
        if candidate.id in seen:
            continue
        seen.add(candidate.id)
        try:
            return generate_structured(
                template,
                params,
                candidate,
                trace_id=trace_id,
                task_id=task_id,
                template_id=template_id,
                tenant_id=tenant_id,
            )
        except Exception as exc:  # noqa: BLE001 —— 降级需捕获任意生成异常
            last_error = exc
            continue

    # 全部候选失败，最后用内置默认模型名兜底一次
    if last_error is not None:
        try:
            return generate_structured(
                template,
                params,
                None,
                trace_id=trace_id,
                task_id=task_id,
                template_id=template_id,
                tenant_id=tenant_id,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    raise ModelRoutingError(f"模型路由降级后仍生成失败，最后错误: {last_error}", last_error)

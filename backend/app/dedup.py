# app/dedup.py —— 生成任务去重指纹
# 纯逻辑模块（不依赖 DB/API），便于单测。
import hashlib
import json
from typing import Any, Dict, Optional


def compute_request_hash(
    template_id: str, params: Dict[str, Any], schema_version: Optional[str] = None
) -> str:
    """计算生成任务的去重指纹：template_id + 规范化参数哈希 + schema 版本。

    参数按 key 排序后 JSON 序列化，保证同一语义参数得到稳定指纹；
    非序列化值（如 datetime）用 str() 兜底。

    schema_version 可选参数用于在模板升级后区分新旧版本的生成任务，
    避免新版本参数与旧版本任务误判为重复。
    """
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    payload = f"{template_id}|{canonical}"
    if schema_version:
        payload = f"{payload}|{schema_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

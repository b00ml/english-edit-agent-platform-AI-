# app/engine/observability.py —— Trace 分发 Sink（P0-5 / OPT-017）
# 自研 TraceLog 表为事实源（SSOT），Langfuse 为可选导出通道：
#   - TraceLogSink：写自研 TraceLog 表（独立会话，失败不影响业务）；
#   - LangfuseSink：LANGFUSE_* 未配置或 SDK 未安装时为 no-op，配置后按
#     trace_id 聚合上传 generation（stage/model/输入输出/token/耗时）。
# record_trace（trace.py）按 settings.TRACE_SINKS 把 trace dict 分发到各 Sink，
# 任一 Sink 抛错只记告警，不中断其余 Sink 与生成主流程。
import logging
from typing import Any, Dict, Protocol

logger = logging.getLogger("app.engine.observability")


class TraceSink(Protocol):
    """Trace 分发协议：emit 接收完整 trace dict，自行负责落存储。"""

    def emit(self, trace: Dict[str, Any]) -> None: ...


class TraceLogSink:
    """自研 TraceLog 表写入（SSOT）。"""

    def emit(self, trace: Dict[str, Any]) -> None:
        # 延迟导入：便于测试替换 SessionLocal，也避免循环依赖
        from app.database import SessionLocal
        from app.models import TraceLog

        session = SessionLocal()
        try:
            session.add(TraceLog(**trace))
            session.commit()
        finally:
            session.close()


class LangfuseSink:
    """Langfuse 可选导出：未配置密钥或 SDK 未安装时静默降级为 no-op。"""

    def __init__(self) -> None:
        self._client: Any = None
        self._init_tried = False

    def _get_client(self) -> Any:
        """惰性初始化 Langfuse 客户端；不可用时返回 None（no-op）。"""
        if self._init_tried:
            return self._client
        self._init_tried = True
        from app.config import settings

        if not (
            settings.LANGFUSE_HOST and settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY
        ):
            return None
        try:
            from langfuse import Langfuse
        except ImportError:
            logger.warning("langfuse 包未安装，LangfuseSink 降级为 no-op")
            return None
        self._client = Langfuse(
            host=settings.LANGFUSE_HOST,
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
        )
        return self._client

    def emit(self, trace: Dict[str, Any]) -> None:
        client = self._get_client()
        if client is None:
            return
        stage = trace.get("stage") or "llm_call"
        latency_ms = trace.get("latency_ms")
        usage = None
        if trace.get("prompt_tokens") is not None:
            usage = {
                "input": trace.get("prompt_tokens") or 0,
                "output": trace.get("completion_tokens") or 0,
                "unit": "TOKENS",
            }
        lf_trace = client.trace(
            id=trace.get("trace_id"),
            name=stage,
            metadata={
                "task_id": trace.get("task_id"),
                "template_id": trace.get("template_id"),
                "prompt_version": trace.get("prompt_version"),
                "attempt": trace.get("attempt"),
                "success": trace.get("success"),
            },
        )
        lf_trace.generation(
            name=stage,
            model=trace.get("model"),
            input=trace.get("input_data"),
            output=trace.get("output_data"),
            usage=usage,
            latency=(latency_ms / 1000.0) if latency_ms is not None else None,
        )

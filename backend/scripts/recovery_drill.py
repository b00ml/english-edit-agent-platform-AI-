"""可复制的 PostgresSaver checkpoint 与 Outbox 恢复演练。"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any, TypedDict

# 兼容 `python scripts/recovery_drill.py` 直接文件入口。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import GenerationTask, QuestionTemplate, TaskOutbox
from app.outbox import relay_pending, replay_dead


class DrillState(TypedDict, total=False):
    """演练图状态。"""

    counter: int
    decision: dict[str, Any]
    status: str


def _open_checkpointer() -> tuple[Any, Any]:
    """打开新的 PostgresSaver 连接，确保 resume 使用新进程等价的连接。"""
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    dsn = settings.DATABASE_URL.replace("+psycopg2", "")
    connection = psycopg.connect(
        dsn,
        autocommit=True,
        prepare_threshold=0,
        connect_timeout=5,
    )
    saver = PostgresSaver(connection)
    saver.setup()
    return connection, saver


def _build_drill_graph(checkpointer: Any) -> Any:
    """构建只包含一个 interrupt 的最小持久化图。"""
    builder = StateGraph(DrillState)

    def increment(state: DrillState) -> dict[str, int]:
        return {"counter": int(state.get("counter", 0)) + 1}

    def approval(state: DrillState) -> dict[str, dict[str, Any]]:
        decision = interrupt({"kind": "recovery-drill", "counter": state.get("counter", 0)})
        return {"decision": decision}

    def finish(state: DrillState) -> dict[str, str]:
        return {"status": "approved" if state.get("decision", {}).get("approved") else "rejected"}

    builder.add_node("increment", increment)
    builder.add_node("approval", approval)
    builder.add_node("finish", finish)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", "approval")
    builder.add_edge("approval", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


def checkpoint_start(thread_id: str) -> None:
    """启动演练图并在 interrupt 处持久化。"""
    connection, saver = _open_checkpointer()
    try:
        graph = _build_drill_graph(saver)
        result = graph.invoke(
            {"counter": 0},
            config={"configurable": {"thread_id": thread_id}},
        )
        if not result.get("__interrupt__"):
            raise RuntimeError("checkpoint start 未产生 interrupt")
        print(f"checkpoint_started thread_id={thread_id} counter={result.get('counter')}")
    finally:
        connection.close()


def checkpoint_resume(thread_id: str) -> None:
    """使用新连接恢复同一 thread，证明检查点可跨进程读取。"""
    connection, saver = _open_checkpointer()
    try:
        graph = _build_drill_graph(saver)
        result = graph.invoke(
            Command(resume={"approved": True}),
            config={"configurable": {"thread_id": thread_id}},
        )
        if result.get("status") != "approved" or result.get("counter") != 1:
            raise RuntimeError(f"checkpoint resume 结果不符合预期: {result}")
        print(
            f"checkpoint_resumed thread_id={thread_id} status={result['status']} counter={result['counter']}"
        )
    finally:
        connection.close()


def outbox_drill(session: Session) -> None:
    """创建临时 dead 事件，重放并用可观测 sender 验证 relay 幂等 task id。"""
    suffix = uuid.uuid4().hex[:12]
    template_id = f"recovery-drill-{suffix}"
    task_id = f"recovery-drill-{suffix}"
    event_id = f"recovery-drill-event-{suffix}"
    template = QuestionTemplate(
        id=template_id,
        type_id=template_id,
        name="recovery drill",
        version=1,
        input_schema={},
        output_schema={},
        quality_rules=[],
        gen_prompt={},
        run_config={},
        status="enabled",
    )
    task = GenerationTask(
        id=task_id,
        template_id=template_id,
        params={},
        quantity=1,
        status="pending",
        tenant_id="recovery-drill",
    )
    event = TaskOutbox(
        id=f"recovery-outbox-{suffix}",
        event_id=event_id,
        task_id=task_id,
        event_type="generation_dispatch",
        payload={"task_id": task_id},
        status="dead",
        attempts=settings.OUTBOX_MAX_ATTEMPTS,
        last_error="synthetic broker failure",
    )
    try:
        session.add(template)
        session.flush()
        session.add(task)
        session.flush()
        session.add(event)
        session.commit()
        replay_dead(session, event.id)
        sent: list[tuple[str, list[str], str | None]] = []

        def sender(name: str, args: list[str], task_id: str | None = None) -> None:
            sent.append((name, args, task_id))

        result = relay_pending(session, sender, limit=1)
        if result["sent"] != 1 or not sent or sent[0][2] != event_id:
            raise RuntimeError(f"outbox relay 结果不符合预期: result={result}, sent={sent}")
        print(f"outbox_replayed event_id={event_id} status=sent celery_task_id={sent[0][2]}")
    finally:
        session.query(TaskOutbox).filter(TaskOutbox.id == event.id).delete(
            synchronize_session=False
        )
        session.query(GenerationTask).filter(GenerationTask.id == task.id).delete(
            synchronize_session=False
        )
        session.query(QuestionTemplate).filter(QuestionTemplate.id == template.id).delete(
            synchronize_session=False
        )
        session.commit()


def main() -> int:
    """执行指定恢复演练阶段。"""
    parser = argparse.ArgumentParser(description="Run checkpoint/outbox recovery drills")
    parser.add_argument(
        "--phase",
        choices=("checkpoint-start", "checkpoint-resume", "outbox"),
        required=True,
    )
    parser.add_argument("--thread-id", help="checkpoint-start/resume 使用的 thread_id")
    args = parser.parse_args()
    try:
        if args.phase == "checkpoint-start":
            checkpoint_start(args.thread_id or f"recovery-drill:{uuid.uuid4()}")
        elif args.phase == "checkpoint-resume":
            if not args.thread_id:
                parser.error("checkpoint-resume 必须提供 --thread-id")
            checkpoint_resume(args.thread_id)
        else:
            session = SessionLocal()
            try:
                outbox_drill(session)
            finally:
                session.close()
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: recovery drill failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

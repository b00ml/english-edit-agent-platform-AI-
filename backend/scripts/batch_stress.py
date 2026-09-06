# scripts/batch_stress.py —— 批量任务稳定性压测
# 用途：一次性入队 N 个生成任务，轮询直至全部到达终态（succeeded/partially_succeeded/failed），
# 校验「大批量稳定完成，无超时丢任务」。任一条目在超时内未到达终态则判定失败并返回非零退出码。
#
# 用法（在 backend 容器内执行，具备 DB 与 Redis 访问）：
#   python scripts/batch_stress.py --quantity 500 --timeout 1200
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

# 脚本位于 backend/scripts 下，需将 backend 根加入模块搜索路径以导入 app.*
sys.path.insert(0, __file__.rsplit("/", 1)[0] + "/..")

from app.database import SessionLocal  # noqa: E402
from app.models import GenerationTask  # noqa: E402
from app.worker.celery_app import celery_app  # noqa: E402

# 终态集合：到达即视为任务已完成
TERMINAL = {"succeeded", "partially_succeeded", "failed"}


def parse_args():
    p = argparse.ArgumentParser(description="批量任务稳定性压测")
    p.add_argument("--quantity", type=int, default=20, help="入队任务数")
    p.add_argument("--timeout", type=int, default=1200, help="等待全部完成的超时秒数")
    p.add_argument("--template-id", default="single_choice", help="题型模板 type_id")
    p.add_argument("--quantity-per-task", type=int, default=1, help="每个任务生成的条数")
    return p.parse_args()


def enqueue_batch(db, quantity: int, template_id: str, per_task: int) -> list[str]:
    """入队批量任务，返回任务 id 列表。

    先一次性提交所有任务行，再逐条投递 Celery 任务，避免 worker 在事务提交前
    因其独立事务看不到未提交行而误判「任务不存在」导致任务假死。
    """
    ids: list[str] = []
    for _ in range(quantity):
        task = GenerationTask(
            template_id=template_id,
            params={
                "knowledge_point": "虚拟语气",
                "difficulty": "medium",
                "quantity": per_task,
            },
            request_hash=None,  # 压测刻意绕过去重
            quantity=per_task,
            status="pending",
            progress=0.0,
        )
        db.add(task)
        db.flush()
        ids.append(task.id)
    db.commit()  # 先提交，确保 worker 一定能查到任务

    for task_id in ids:
        celery_app.send_task("app.worker.tasks.process_generation_task", args=[task_id])
    return ids


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        ids = enqueue_batch(db, args.quantity, args.template_id, args.quantity_per_task)
        print(f"[压测] 已入队 {len(ids)} 个任务，开始监控…", flush=True)

        deadline = datetime.now(timezone.utc) + timedelta(seconds=args.timeout)
        remaining = set(ids)
        done: dict[str, dict] = {}
        while remaining and datetime.now(timezone.utc) < deadline:
            rows = db.query(GenerationTask).filter(GenerationTask.id.in_(remaining)).all()
            for r in rows:
                if r.status in TERMINAL:
                    done[r.id] = {
                        "status": r.status,
                        "progress": r.progress,
                        "elapsed": (datetime.now(timezone.utc) - r.created_at).total_seconds(),
                    }
                    remaining.discard(r.id)
            if remaining:
                time.sleep(2)
        db.close()

        total = len(ids)
        terminal = len(done)
        stuck = len(remaining)
        status_counter: dict[str, int] = {}
        for meta in done.values():
            status_counter[meta["status"]] = status_counter.get(meta["status"], 0) + 1

        print(f"[压测结果] 共 {total} 个任务")
        print(f"  到达终态: {terminal}（{terminal / total * 100:.1f}%）")
        print(f"  仍未完成(丢任务): {stuck}")
        print(f"  状态分布: {status_counter or '(无)'}")
        if stuck:
            print(f"[压测失败] {stuck} 个任务在 {args.timeout}s 内未完成", flush=True)
            return 1
        print("[压测通过] 全部任务稳定完成，无超时丢任务", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 —— 压测脚本需兜底并给出非零退出码
        print(f"[压测异常] {exc}")
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

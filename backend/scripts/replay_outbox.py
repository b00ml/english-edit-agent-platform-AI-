"""重放指定 task_outbox 死信事件。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.outbox import replay_dead


def main() -> int:
    """只把 dead 事件恢复为 pending，不直接执行投递。"""
    parser = argparse.ArgumentParser(description="Replay a dead outbox event")
    parser.add_argument("event_id", help="task_outbox.id")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        event = replay_dead(session, args.event_id)
        print(f"replayed event_id={event.id} event_key={event.event_id} status={event.status}")
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

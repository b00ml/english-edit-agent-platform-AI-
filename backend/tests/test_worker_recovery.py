# tests/test_worker_recovery.py —— 僵尸任务恢复 + Celery 可靠性配置单测（P0-6 / OPT-019）
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.config import settings
from app.worker.celery_app import celery_app
from app.worker.recovery import recover_stale_tasks
from app.worker.tasks import process_generation_task


class _FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class TestRecoverStaleTasks:
    def test_stale_task_reset_and_enqueued(self, monkeypatch):
        stale = [
            SimpleNamespace(id="task-1", status="running"),
            SimpleNamespace(id="task-2", status="running"),
        ]
        monkeypatch.setattr("app.worker.recovery._select_stale", lambda session, cutoff: stale)
        session = _FakeSession()
        enqueued = []
        count = recover_stale_tasks(session, enqueue=enqueued.append)
        assert count == 2
        assert enqueued == ["task-1", "task-2"]
        assert all(t.status == "pending" for t in stale)
        assert session.commits == 2

    def test_no_stale_task_noop(self, monkeypatch):
        monkeypatch.setattr("app.worker.recovery._select_stale", lambda s, c: [])
        session = _FakeSession()
        enqueued = []
        count = recover_stale_tasks(session, enqueue=enqueued.append)
        assert count == 0 and enqueued == [] and session.commits == 0

    def test_cutoff_uses_stale_seconds(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(settings, "STALE_TASK_SECONDS", 600)

        def _fake_select(session, cutoff):
            captured["cutoff"] = cutoff
            return []

        monkeypatch.setattr("app.worker.recovery._select_stale", _fake_select)
        now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        recover_stale_tasks(_FakeSession(), now=now, enqueue=lambda tid: None)
        assert captured["cutoff"] == now - timedelta(seconds=600)


class TestCeleryReliabilityConfig:
    def test_task_delivery_semantics(self):
        # 执行完才 ack；worker 崩溃消息重投
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.task_reject_on_worker_lost is True
        # 可见性超时须大于硬超时 900s
        assert celery_app.conf.broker_transport_options["visibility_timeout"] > 900

    def test_task_retry_semantics(self):
        assert process_generation_task.max_retries == settings.TASK_MAX_RETRIES
        assert process_generation_task.acks_late is True
        autoretry = getattr(process_generation_task, "autoretry_for", ())
        names = {getattr(e, "__name__", str(e)) for e in autoretry}
        assert "ConnectionError" in names
        assert "TimeoutError" in names
        assert "OperationalError" in names

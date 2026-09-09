from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.errors import NotFoundError, TenantScopeDeniedError
from app.models import AppNotification, ContentItem, GenerationTask
from app.notification import (
    build_task_notification,
    notify_content_rejected,
    notify_human_review,
    notify_task_result,
)
from app.services.generation_service import GenerationService
from app.services.knowledge_service import KnowledgeService
from app.services.sample_service import SampleService
from app.services.trace_service import TraceService


def _user(tenant_id="tenant-1"):
    return SimpleNamespace(id="u1", tenant_id=tenant_id, role="researcher")


def test_knowledge_service_upload_and_query_paths(monkeypatch):
    db = SimpleNamespace()
    service = KnowledgeService(db)
    user = _user()
    monkeypatch.setattr("app.services.knowledge_service.index_document", lambda *a, **k: 2)
    assert service.upload_text("hello", "教材", "book", "时态", {"x": 1}, user)["chunks"] == 2
    monkeypatch.setattr("app.services.knowledge_service.parse_file", lambda *a, **k: "parsed")
    out = service.upload_file("book.txt", b"data", "教材", "时态", user)
    assert out["source_name"] == "book"
    with pytest.raises(Exception):
        service.upload_text("  ", "教材", "book", None, None, user)
    with pytest.raises(Exception):
        service.upload_file("", b"x", "教材", None, user)
    with pytest.raises(Exception):
        service.upload_file("a.txt", b"", "教材", None, user)
    with pytest.raises(Exception):
        service.upload_file("a.txt", b"x" * (10 * 1024 * 1024 + 1), "教材", None, user)


def test_knowledge_service_crud_and_retrieve(monkeypatch):
    now = datetime.now(timezone.utc)
    chunk = SimpleNamespace(
        id="c1",
        text="short",
        source="book",
        metadata={"a": 1},
        meta={"a": 1},
        created_at=now,
        tenant_id="tenant-1",
    )

    class Repo:
        def create(self, **kwargs):
            return chunk

        def list_by_tenant(self, **kwargs):
            return [chunk]

        def count_by_tenant(self, **kwargs):
            return 1

        def get_by_id(self, value):
            return chunk if value == "c1" else None

        def delete(self, value):
            return None

    class DB:
        def commit(self):
            pass

        def refresh(self, value):
            pass

        def delete(self, value):
            pass

    db = DB()
    service = KnowledgeService(db)
    service.knowledge_repo = Repo()
    user = _user()
    assert service.create_chunk("text", "src", None, None, user)["id"] == "c1"
    assert service.list_chunks(user)["total"] == 1
    assert service.retrieve("q", user)[0]["score"] == 0.9
    service.delete_chunk("c1", user)
    with pytest.raises(NotFoundError):
        service.delete_chunk("missing", user)
    foreign = _user("tenant-2")
    with pytest.raises(TenantScopeDeniedError):
        service.delete_chunk("c1", foreign)
    monkeypatch.setattr(
        "app.services.knowledge_service.rag_retrieve", lambda *a, **k: [{"text": "x"}]
    )
    assert service.retrieve_knowledge("q", None, 3, user)["snippets"]


def test_sample_service_paths(monkeypatch):
    item = SimpleNamespace(id="i1", status="passed", template_id="single_choice")
    sample = SimpleNamespace(
        id="s1",
        template_id="single_choice",
        knowledge_point="时态",
        purpose="fewshot",
        source="manual",
        payload={"q": 1},
        meta={},
        content_id="i1",
        quality_score=0.9,
        metadata={},
        created_at=datetime.now(timezone.utc),
        tenant_id="tenant-1",
    )

    class DB:
        def get(self, cls, ident):
            return item if ident == "i1" else None

        def commit(self):
            pass

        def refresh(self, obj):
            pass

        def query(self, cls):
            return SimpleNamespace(scalar=lambda: 1)

    db = DB()
    service = SampleService(db)
    user = _user()
    monkeypatch.setattr("app.services.sample_service._pool_item", lambda *a, **k: sample)
    monkeypatch.setattr("app.services.sample_service._sync_eligible", lambda db: 1)
    monkeypatch.setattr("app.services.sample_service._list_samples", lambda *a, **k: ([sample], 1))
    removed = {"value": True}
    monkeypatch.setattr(
        "app.services.sample_service._remove_sample", lambda *a, **k: removed.pop("value", False)
    )
    assert service.create_sample_from_content("i1", "manual", "fewshot", user).id == "s1"
    assert service.sync_samples(user)["added"] == 1
    assert service.list_samples_filtered(None, None, None, None, 1, 10, user)[1] == 1
    assert (
        service.export_samples_jsonl(None, None, None, None, user)[0]["template_id"]
        == "single_choice"
    )
    assert service.delete_sample_by_id("s1", user)["deleted"] == "s1"
    with pytest.raises(NotFoundError):
        service.delete_sample_by_id("s1", user)


def test_sample_service_legacy_paths():
    now = datetime.now(timezone.utc)
    sample = SimpleNamespace(
        id="s1",
        content_id="i1",
        template_id="t1",
        quality_score=0.9,
        metadata={},
        created_at=now,
        tenant_id="tenant-1",
    )

    class Repo:
        def create(self, **kwargs):
            return sample

        def list_by_tenant(self, **kwargs):
            return [sample]

        def count_by_tenant(self, **kwargs):
            return 1

        def get_by_id(self, ident):
            return sample if ident == "s1" else None

        def delete(self, obj):
            pass

        def sync_from_content(self, **kwargs):
            return 2

    class DB:
        def commit(self):
            pass

        def refresh(self, obj):
            pass

    service = SampleService(DB())
    service.sample_repo = Repo()
    user = _user()
    assert service.create_sample("i1", "t1", 0.9, None, user)["id"] == "s1"
    assert service.list_samples(user)["total"] == 1
    assert service.sync_from_content(user)["synced_count"] == 2
    assert service.export_samples(user)[0]["id"] == "s1"
    service.delete_sample("s1", user)
    with pytest.raises(NotFoundError):
        service.delete_sample("missing", user)
    with pytest.raises(TenantScopeDeniedError):
        service.delete_sample("s1", _user("tenant-2"))


def test_trace_service_reports():
    now = datetime.now(timezone.utc)
    trace = SimpleNamespace(
        trace_id="tr1",
        model="m1",
        total_cost=0.2,
        input_tokens=2,
        output_tokens=3,
        operation="generate",
        latency_ms=10,
        created_at=now,
    )

    class Traces:
        def list_by_tenant(self, **kwargs):
            return [trace]

        def count_by_tenant(self, **kwargs):
            return 1

        def aggregate_by_model(self, **kwargs):
            return [{"total_cost": 0.2, "total_tokens": 5}]

        def aggregate_by_date(self, **kwargs):
            return []

        def sum_cost(self, **kwargs):
            return 0.2

        def structured_output_stats(self, **kwargs):
            return {"total": 2, "success_rate": 0.5, "retry_rate": 0.5, "by_model": []}

        def get_by_trace_id(self, **kwargs):
            return [
                SimpleNamespace(
                    id="1",
                    trace_id="tr1",
                    model="m1",
                    operation="generate",
                    input_tokens=1,
                    output_tokens=2,
                    total_cost=0.1,
                    latency_ms=3,
                    prompt="p",
                    response="r",
                    error=None,
                    created_at=now,
                )
            ]

    class Tasks:
        def count_by_status(self, **kwargs):
            return {"succeeded": 1}

    class Contents:
        def count_status_summary(self, **kwargs):
            return {"passed": 1}

    service = TraceService(SimpleNamespace())
    service.trace_repo = Traces()
    service.task_repo = Tasks()
    service.content_repo = Contents()
    user = _user()
    assert service.list_costs(user)[0]["trace_id"] == "tr1"
    assert service.get_deep_cost(user)["total_tokens"] == 5
    assert service.get_dashboard(user)["cost_7d"] == 0.2
    assert service.list_traces(user)["total"] == 1
    assert service.get_structured_stats(user)["retry_rate"] == 0.5
    assert service.get_trace_detail("tr1", user)[0]["prompt"] == "p"
    service.trace_repo.get_by_trace_id = lambda **kwargs: []
    assert service.get_trace_detail("missing", user) == []


def test_notification_build_and_idempotency(db):
    now = datetime.now(timezone.utc)
    task = GenerationTask(id="t1", quantity=2, tenant_id="tenant-1", status="succeeded")
    assert build_task_notification(task).type == "task_succeeded"
    task.status = "partially_succeeded"
    assert build_task_notification(task).type == "task_partial"
    task.status = "failed"
    assert build_task_notification(task).type == "task_failed"
    task.status = "running"
    assert build_task_notification(task) is None
    task.status = "succeeded"
    notify_task_result(db, task)
    notify_task_result(db, task)
    item = ContentItem(id="i1", tenant_id="tenant-1")
    notify_content_rejected(db, item, "bad")
    notify_content_rejected(db, item, "bad")
    notify_human_review(db, item, 65)
    notify_human_review(db, item, 65)
    assert db.query(AppNotification).count() == 3


def test_generation_service_query_and_status_contracts():
    now = datetime.now(timezone.utc)
    task = SimpleNamespace(
        id="t1",
        template_id="single_choice",
        params={"level": "A1"},
        quantity=1,
        status="pending",
        progress=0.0,
        trace_ref=None,
        tenant_id="tenant-1",
        created_at=now,
        updated_at=now,
    )

    class Repo:
        def get_by_id(self, task_id):
            return task if task_id == "t1" else None

        def list_by_user(self, *args):
            return [task]

        def count_by_user(self, *args):
            return 1

        def list_by_tenant(self, *args):
            return [task]

        def count_by_tenant(self, *args):
            return 1

        def list_all(self, *args):
            return [task]

        def count(self):
            return 1

        def update(self, instance, **kwargs):
            for key, value in kwargs.items():
                setattr(instance, key, value)

    class DB:
        def commit(self):
            pass

        def refresh(self, instance):
            pass

    service = GenerationService(DB())
    service.task_repo = Repo()
    assert service.get_task("t1") is task
    with pytest.raises(Exception):
        service.get_task("missing")
    assert service.list_tasks(user_id="u1").total == 1
    assert service.list_tasks(tenant_id="tenant-1").total == 1
    assert service.list_tasks().total == 1
    assert service.update_task_status("t1", "running", 0.5).status == "running"
    assert task.progress == 0.5
    with pytest.raises(Exception):
        service.update_task_status("missing", "failed")

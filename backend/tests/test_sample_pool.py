# tests/test_sample_pool.py —— 高质量回流样本（J2）纯逻辑单测
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as ORMSession

from app.models import ContentItem, GenerationTask, SamplePool
from app.sample_pool import (
    is_eligible,
    list_samples,
    pool_item,
    remove_sample,
    sync_eligible,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    """SQLite 测试环境将 JSONB 编译为 JSON，便于内存表建表。"""
    return "JSON"


@pytest.fixture
def session():
    """返回含 content_item/generation_task/sample_pool 表的内存 SQLite 会话。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SamplePool.__table__.create(bind=engine)
    ContentItem.__table__.create(bind=engine)
    GenerationTask.__table__.create(bind=engine)
    with ORMSession(engine) as s:
        s.add(
            GenerationTask(
                id="task-1",
                template_id="single_choice",
                params={"knowledge_point": "一般现在时", "difficulty": "medium"},
                quantity=1,
            )
        )
        s.add_all(
            [
                ContentItem(
                    id="c-passed",
                    task_id="task-1",
                    template_id="single_choice",
                    payload={"question": "Q1"},
                    qc_score=95.0,
                    status="passed",
                ),
                ContentItem(
                    id="c-published",
                    task_id="task-1",
                    template_id="single_choice",
                    payload={"question": "Q2"},
                    qc_score=92.0,
                    status="published",
                ),
                ContentItem(
                    id="c-pending",
                    task_id="task-1",
                    template_id="single_choice",
                    payload={"question": "Q3"},
                    qc_score=80.0,
                    status="pending_qc",
                ),
            ]
        )
        s.commit()
        yield s


class TestIsEligible:
    def test_passed_eligible(self, session):
        item = session.get(ContentItem, "c-passed")
        assert is_eligible(item) is True

    def test_published_eligible(self, session):
        item = session.get(ContentItem, "c-published")
        assert is_eligible(item) is True

    def test_pending_not_eligible(self, session):
        item = session.get(ContentItem, "c-pending")
        assert is_eligible(item) is False


class TestPoolItem:
    def test_pool_creates_sample_with_knowledge_point(self, session):
        item = session.get(ContentItem, "c-passed")
        sample = pool_item(session, item, source="manual", purpose="sft")
        assert sample.item_id == "c-passed"
        assert sample.template_id == "single_choice"
        assert sample.knowledge_point == "一般现在时"
        assert sample.payload == {"question": "Q1"}
        assert sample.meta["qc_score"] == 95.0

    def test_pool_idempotent(self, session):
        item = session.get(ContentItem, "c-passed")
        s1 = pool_item(session, item)
        s2 = pool_item(session, item)
        assert s1.id == s2.id
        assert session.query(SamplePool).count() == 1


class TestSyncEligible:
    def test_sync_pools_only_eligible(self, session):
        added = sync_eligible(session)
        assert added == 2  # c-passed + c-published
        rows, total = list_samples(session, page=1, page_size=20)
        assert total == 2

    def test_sync_idempotent(self, session):
        sync_eligible(session)
        added = sync_eligible(session)
        assert added == 0  # 已沉淀，不再重复


class TestListSamples:
    def test_filter_by_knowledge_point(self, session):
        sync_eligible(session)
        rows, total = list_samples(session, knowledge_point="一般现在时")
        assert total == 2

    def test_filter_by_source(self, session):
        sync_eligible(session)
        rows, total = list_samples(session, source="auto")
        assert total == 2
        rows_manual, total_manual = list_samples(session, source="manual")
        assert total_manual == 0


class TestRemoveSample:
    def test_remove_existing(self, session):
        sync_eligible(session)
        sample = session.query(SamplePool).first()
        assert remove_sample(session, sample.id) is True
        assert session.query(SamplePool).count() == 1

    def test_remove_missing(self, session):
        assert remove_sample(session, "no-such") is False

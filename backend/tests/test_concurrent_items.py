# tests/test_concurrent_items.py —— 并发 item 执行测试（P1-3）
import pytest
from sqlalchemy.orm import Session

from app.models import ContentItem, GenerationTask, GenerationTaskItem, QuestionTemplate
from app.worker.tasks import dispatch_generation_items, generate_single_item


@pytest.fixture
def batch_task(db: Session):
    """创建批量任务。"""
    db.add(
        QuestionTemplate(
            id="single_choice",
            type_id="single_choice",
            name="单选题",
            version=1,
            input_schema={},
            output_schema={},
            quality_rules={},
            gen_prompt="",
            run_config={},
            status="active",
            tenant_id="test-tenant",
        )
    )
    db.commit()
    task = GenerationTask(
        id="test-batch-001",
        template_id="single_choice",
        params={"difficulty": "easy"},
        quantity=10,
        status="pending",
        tenant_id="test-tenant",
    )
    db.add(task)
    db.commit()
    for content_id in ["content-001", *[f"content-{idx}" for idx in range(10)]]:
        db.add(
            ContentItem(
                id=content_id,
                task_id=task.id,
                template_id="single_choice",
                payload={},
                tenant_id="test-tenant",
            )
        )
    db.commit()
    return task


def test_single_item_execution(db: Session, batch_task: GenerationTask, monkeypatch):
    """测试单个 item 正常执行。"""
    # 先调度
    dispatch_generation_items.apply(args=[batch_task.id]).get()

    # Mock run_generation 返回成功结果
    def mock_run_generation(*args, **kwargs):
        return {"status": "stored", "content_id": "content-001"}

    monkeypatch.setattr("app.worker.tasks.run_generation", mock_run_generation)

    # 执行单个 item
    result = generate_single_item.apply(args=[batch_task.id, 0]).get()
    assert result["status"] == "succeeded"
    assert result["content_id"] == "content-001"

    # 验证 item 记录
    item = (
        db.query(GenerationTaskItem)
        .filter(
            GenerationTaskItem.task_id == batch_task.id,
            GenerationTaskItem.item_index == 0,
        )
        .first()
    )
    assert item.status == "succeeded"
    assert item.content_id == "content-001"
    assert item.attempts == 1


def test_concurrent_item_dispatch(db: Session, batch_task: GenerationTask):
    """测试批量投递 10 个 item。"""
    result = dispatch_generation_items.apply(args=[batch_task.id]).get()
    assert result["status"] == "dispatched"
    assert result["total"] == 10

    # 验证 10 个 item 记录已创建
    items = db.query(GenerationTaskItem).filter(GenerationTaskItem.task_id == batch_task.id).all()
    assert len(items) == 10

    # 验证 thread_id 格式
    for idx, item in enumerate(sorted(items, key=lambda x: x.item_index)):
        assert item.thread_id == f"{batch_task.id}:{idx}"
        assert item.status == "pending"


def test_item_idempotency(db: Session, batch_task: GenerationTask, monkeypatch):
    """测试重复投递相同 item 不重复执行。"""
    # 调度
    dispatch_generation_items.apply(args=[batch_task.id]).get()

    # Mock run_generation
    mock_call_count = {"count": 0}

    def mock_run_generation(*args, **kwargs):
        mock_call_count["count"] += 1
        return {"status": "stored", "content_id": f"content-{mock_call_count['count']}"}

    monkeypatch.setattr("app.worker.tasks.run_generation", mock_run_generation)

    # 第一次执行
    result1 = generate_single_item.apply(args=[batch_task.id, 0]).get()
    assert result1["status"] == "succeeded"
    assert mock_call_count["count"] == 1

    # 第二次执行（重复投递）
    result2 = generate_single_item.apply(args=[batch_task.id, 0]).get()
    assert result2["status"] == "succeeded"
    assert "已完成，跳过重复执行" in result2["reason"]
    assert mock_call_count["count"] == 1  # 未重复调用


def test_partial_success(db: Session, batch_task: GenerationTask, monkeypatch):
    """测试部分 item 失败不影响成功的 item。"""
    # 调度
    dispatch_generation_items.apply(args=[batch_task.id]).get()

    # Mock run_generation：奇数 item 成功，偶数 item 失败
    def mock_run_generation(*args, **kwargs):
        thread_id = kwargs.get("thread_id", "")
        item_index = int(thread_id.split(":")[-1])
        if item_index % 2 == 0:
            raise Exception("422 Unprocessable Entity: Mock permanent error")
        return {"status": "stored", "content_id": f"content-{item_index}"}

    monkeypatch.setattr("app.worker.tasks.run_generation", mock_run_generation)

    # 执行所有 item
    results = []
    for idx in range(10):
        try:
            result = generate_single_item.apply(args=[batch_task.id, idx]).get()
            results.append(result)
        except Exception as e:
            results.append({"status": "failed", "reason": str(e)})

    # 验证结果：奇数成功，偶数失败
    succeeded = [r for r in results if r.get("status") == "succeeded"]
    failed = [r for r in results if r.get("status") == "failed"]
    assert len(succeeded) == 5
    assert len(failed) == 5

    # 验证父任务状态
    db.refresh(batch_task)
    assert batch_task.status == "partially_succeeded"
    assert batch_task.progress == 1.0  # 全部完成（包括失败的）

# tests/test_notification.py —— 站内通知纯逻辑单测
from app.models import GenerationTask
from app.notification import build_task_notification


def _task(status: str) -> GenerationTask:
    return GenerationTask(
        id="t-1",
        template_id="single_choice",
        quantity=3,
        status=status,
        progress=1.0,
    )


class TestBuildTaskNotification:
    def test_succeeded(self):
        n = build_task_notification(_task("succeeded"))
        assert n is not None
        assert n.type == "task_succeeded"
        assert n.title == "生成任务完成"
        assert "3" in n.content
        assert n.related_id == "t-1"

    def test_partially_succeeded(self):
        n = build_task_notification(_task("partially_succeeded"))
        assert n is not None
        assert n.type == "task_partial"

    def test_failed(self):
        n = build_task_notification(_task("failed"))
        assert n is not None
        assert n.type == "task_failed"

    def test_running_no_notification(self):
        # 执行中状态不产生通知
        assert build_task_notification(_task("running")) is None

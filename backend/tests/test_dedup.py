# tests/test_dedup.py —— 重复提交去重指纹逻辑单测
from app.dedup import compute_request_hash


class TestComputeRequestHash:
    def test_same_params_same_hash(self):
        h1 = compute_request_hash("single_choice", {"topic": "greeting", "level": 2})
        h2 = compute_request_hash("single_choice", {"topic": "greeting", "level": 2})
        assert h1 == h2

    def test_param_order_insensitive(self):
        h1 = compute_request_hash("single_choice", {"topic": "greeting", "level": 2})
        h2 = compute_request_hash("single_choice", {"level": 2, "topic": "greeting"})
        assert h1 == h2

    def test_different_params_different_hash(self):
        h1 = compute_request_hash("single_choice", {"topic": "greeting", "level": 2})
        h2 = compute_request_hash("single_choice", {"topic": "greeting", "level": 3})
        assert h1 != h2

    def test_different_template_different_hash(self):
        h1 = compute_request_hash("single_choice", {"topic": "greeting"})
        h2 = compute_request_hash("cloze", {"topic": "greeting"})
        assert h1 != h2

    def test_nested_params_stable(self):
        h1 = compute_request_hash("reading", {"items": [{"q": 1}, {"q": 2}]})
        h2 = compute_request_hash("reading", {"items": [{"q": 1}, {"q": 2}]})
        assert h1 == h2

# tests/test_validation.py —— 模板校验与文本分块纯逻辑单测
from app.rag.indexer import chunk_text
from app.template_loader import _validate_template

VALID_TEMPLATE = {
    "type_id": "single_choice",
    "name": "单项选择",
    "version": 1,
    "input_schema": {"type": "object", "properties": {}, "required": []},
    "output_schema": {
        "type": "object",
        "required": ["stem", "answer"],
        "properties": {
            "stem": {"type": "string"},
            "answer": {"type": "string"},
        },
    },
    "quality_rules": [{"id": "kp_match", "weight": 0.5}, {"id": "diff", "weight": 0.5}],
    "gen_prompt": {"system": "sys", "user": "usr"},
    "run_config": {"model_profile": "standard", "max_retry": 3},
}


class TestValidateTemplate:
    def test_valid_template_passes(self):
        assert _validate_template(dict(VALID_TEMPLATE)) == []

    def test_missing_required_field(self):
        data = dict(VALID_TEMPLATE)
        data.pop("gen_prompt")
        errors = _validate_template(data)
        assert any("gen_prompt" in e for e in errors)

    def test_bad_weight_sum(self):
        data = dict(VALID_TEMPLATE)
        data["quality_rules"] = [{"id": "a", "weight": 0.9}]
        assert any("权重之和" in e for e in _validate_template(data))

    def test_missing_system_in_gen_prompt(self):
        data = dict(VALID_TEMPLATE)
        data["gen_prompt"] = {"user": "only"}
        assert any("system" in e for e in _validate_template(data))


class TestChunkText:
    def test_short_text_single_chunk(self):
        assert chunk_text("hello world", max_chars=500) == ["hello world"]

    def test_empty_text(self):
        assert chunk_text("   ") == []

    def test_long_text_splits_with_overlap(self):
        text = "a" * 300
        chunks = chunk_text(text, max_chars=100, overlap=10)
        # 300 字符、块 100、重叠 10：足够切出 ≥3 块且首块有重叠
        assert len(chunks) >= 3
        assert all(len(c) <= 100 for c in chunks)

    def test_paragraph_boundary_respected(self):
        text = "x" * 80 + "\n" + "y" * 80 + "\n" + "z" * 80
        chunks = chunk_text(text, max_chars=100, overlap=0)
        # 优先在换行处切分，避免切断段落
        assert all("\n" not in c for c in chunks)

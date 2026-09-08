"""
测试输出 Schema 约束保留（P1-2）
验收标准：
- 数组 minItems/maxItems 约束被保留并校验
- 字符串 enum 约束被保留并校验
- 字符串 minLength/maxLength 约束被保留并校验
- 第二道 jsonschema 校验可兜底 Pydantic 无法表达的约束
"""

import pytest
from pydantic import ValidationError

from app.engine.structured_output import _build_pydantic_from_schema, _map_schema_type


class TestArrayConstraints:
    """测试数组长度约束（minItems/maxItems）。"""

    def test_array_min_items_enforced(self):
        """数组元素不足 minItems 应抛出 ValidationError。"""
        schema = {
            "type": "object",
            "properties": {
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 6,
                }
            },
            "required": ["options"],
        }
        model = _build_pydantic_from_schema(schema)

        # 正常：3 个元素
        valid = model.model_validate({"options": ["A", "B", "C"]})
        assert len(valid.options) == 3

        # 违规：只有 2 个元素（不足 minItems=3）
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate({"options": ["A", "B"]})
        assert (
            "at least 3 items" in str(exc_info.value).lower()
            or "min_length" in str(exc_info.value).lower()
        )

    def test_array_max_items_enforced(self):
        """数组元素超过 maxItems 应抛出 ValidationError。"""
        schema = {
            "type": "object",
            "properties": {
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 4,
                }
            },
            "required": ["options"],
        }
        model = _build_pydantic_from_schema(schema)

        # 正常：4 个元素
        valid = model.model_validate({"options": ["A", "B", "C", "D"]})
        assert len(valid.options) == 4

        # 违规：5 个元素（超过 maxItems=4）
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate({"options": ["A", "B", "C", "D", "E"]})
        assert (
            "at most 4 items" in str(exc_info.value).lower()
            or "max_length" in str(exc_info.value).lower()
        )

    def test_array_without_constraints_accepts_any_length(self):
        """无长度约束的数组应接受任意长度。"""
        schema = {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"type": "string"}}},
            "required": ["items"],
        }
        model = _build_pydantic_from_schema(schema)

        # 空数组、1 个、100 个都应通过
        model.model_validate({"items": []})
        model.model_validate({"items": ["A"]})
        model.model_validate({"items": ["A"] * 100})


class TestStringConstraints:
    """测试字符串约束（enum/minLength/maxLength）。"""

    def test_string_enum_enforced(self):
        """字符串枚举约束应保留并校验。"""
        schema = {
            "type": "object",
            "properties": {"difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]}},
            "required": ["difficulty"],
        }
        model = _build_pydantic_from_schema(schema)

        # 正常：枚举值之一
        valid = model.model_validate({"difficulty": "easy"})
        assert valid.difficulty == "easy"

        # 违规：不在枚举列表中
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate({"difficulty": "超难"})
        assert "input should be" in str(exc_info.value).lower()

    def test_string_min_length_enforced(self):
        """字符串 minLength 约束应保留并校验。"""
        schema = {
            "type": "object",
            "properties": {"stem": {"type": "string", "minLength": 10}},
            "required": ["stem"],
        }
        model = _build_pydantic_from_schema(schema)

        # 正常：10 个字符
        valid = model.model_validate({"stem": "1234567890"})
        assert len(valid.stem) == 10

        # 违规：只有 5 个字符
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate({"stem": "12345"})
        assert (
            "at least 10 characters" in str(exc_info.value).lower()
            or "min_length" in str(exc_info.value).lower()
        )

    def test_string_max_length_enforced(self):
        """字符串 maxLength 约束应保留并校验。"""
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string", "maxLength": 5}},
            "required": ["answer"],
        }
        model = _build_pydantic_from_schema(schema)

        # 正常：5 个字符
        valid = model.model_validate({"answer": "ABCDE"})
        assert len(valid.answer) == 5

        # 违规：6 个字符
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate({"answer": "ABCDEF"})
        assert (
            "at most 5 characters" in str(exc_info.value).lower()
            or "max_length" in str(exc_info.value).lower()
        )


class TestNestedObjectConstraints:
    """测试嵌套对象的约束保留。"""

    def test_nested_array_with_object_items_enforces_min_items(self):
        """嵌套数组（对象元素）的 minItems 约束应保留。"""
        schema = {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "stem": {"type": "string"},
                            "answer": {"type": "string"},
                        },
                        "required": ["stem", "answer"],
                    },
                    "minItems": 2,
                }
            },
            "required": ["questions"],
        }
        model = _build_pydantic_from_schema(schema)

        # 正常：2 个对象
        valid = model.model_validate(
            {
                "questions": [
                    {"stem": "Q1", "answer": "A1"},
                    {"stem": "Q2", "answer": "A2"},
                ]
            }
        )
        assert len(valid.questions) == 2

        # 违规：只有 1 个对象
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate({"questions": [{"stem": "Q1", "answer": "A1"}]})
        assert (
            "at least 2 items" in str(exc_info.value).lower()
            or "min_length" in str(exc_info.value).lower()
        )


class TestMapSchemaTypeConstraints:
    """测试 _map_schema_type 正确保留约束。"""

    def test_string_with_min_max_length_returns_constr(self):
        """字符串带长度约束应返回 constr。"""
        field_type = _map_schema_type({"type": "string", "minLength": 5, "maxLength": 20})
        # 返回的应该是 Pydantic 约束类型，不是普通 str
        assert field_type is not str

    def test_array_with_min_max_items_returns_conlist(self):
        """数组带长度约束应返回 conlist。"""
        field_type = _map_schema_type(
            {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 5,
            }
        )
        # 返回的应该是 Pydantic 约束类型
        assert hasattr(field_type, "__origin__")  # 泛型类型

    def test_string_enum_returns_literal(self):
        """字符串枚举应返回 Literal。"""
        field_type = _map_schema_type({"type": "string", "enum": ["A", "B", "C"]})
        assert field_type is not str
        # Literal 类型检查
        assert hasattr(field_type, "__args__")

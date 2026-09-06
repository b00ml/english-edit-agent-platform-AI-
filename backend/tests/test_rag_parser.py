# tests/test_rag_parser.py —— 知识库文件解析纯逻辑单测（P3/RAG 上传扩展）
import pytest

from app.rag.parser import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFileTypeError,
    parse_file,
)


class TestParseFile:
    def test_txt_utf8(self):
        text = parse_file("试卷.txt", "第一题：单词填空。\n第二题：阅读理解。".encode("utf-8"))
        assert "第一题" in text and "阅读理解" in text

    def test_md(self):
        text = parse_file("讲义.md", "# 语法\n\n现在完成时。".encode("utf-8"))
        assert "现在完成时" in text

    def test_unsupported_type_raises(self):
        with pytest.raises(UnsupportedFileTypeError):
            parse_file("图片.png", b"\x89PNG")

    def test_no_extension_raises(self):
        with pytest.raises(UnsupportedFileTypeError):
            parse_file("README", b"hello")

    def test_empty_txt_returns_empty(self):
        assert parse_file("空.txt", b"") == ""

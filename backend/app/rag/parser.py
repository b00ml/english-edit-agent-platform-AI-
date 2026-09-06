# app/rag/parser.py —— 知识库文件解析
# 将上传的常见教研文档（试卷/练习册等）抽取为纯文本，供分块索引。
from pathlib import Path
from typing import Set

# 允许的扩展名
SUPPORTED_EXTENSIONS: Set[str] = {".txt", ".md", ".docx", ".pdf"}


class UnsupportedFileTypeError(Exception):
    """文件类型不受支持。"""


def parse_file(filename: str, content: bytes) -> str:
    """按扩展名解析文件内容为纯文本。

    支持 txt/md（直接按 UTF-8 读取）、docx（python-docx）、pdf（pypdf）。
    """
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"不支持的文件类型 {ext or '（无扩展名）'}，支持：{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    if ext in (".txt", ".md"):
        return _decode_text(content)
    if ext == ".docx":
        return _parse_docx(content)
    if ext == ".pdf":
        return _parse_pdf(content)
    return ""


def _decode_text(content: bytes) -> str:
    """按 UTF-8（容错回退）解码纯文本。"""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("gb18030", errors="replace")


def _parse_docx(content: bytes) -> str:
    """用 python-docx 解析 .docx，提取所有段落文本。"""
    try:
        import io

        import docx  # type: ignore
    except ImportError as e:  # 依赖未安装
        raise ImportError("解析 .docx 需要安装 python-docx（pip install python-docx）") from e

    document = docx.Document(io.BytesIO(content))
    paragraphs = [p.text for p in document.paragraphs if p.text and p.text.strip()]
    return "\n".join(paragraphs)


def _parse_pdf(content: bytes) -> str:
    """用 pypdf 解析 .pdf，提取所有页面文本。"""
    try:
        import io

        from pypdf import PdfReader  # type: ignore
    except ImportError as e:  # 依赖未安装
        raise ImportError("解析 .pdf 需要安装 pypdf（pip install pypdf）") from e

    reader = PdfReader(io.BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(page for page in pages if page.strip())

# app/rag/indexer.py —— 知识库分块与索引
# 将教材/课标/真题等文本按知识点分块并向量化入库。
from typing import List

from sqlalchemy.orm import Session

from app.models import KnowledgeChunk
from app.rag.embedding import embed_texts

# 分块参数：单块最大字符数与相邻块重叠字符数
_DEFAULT_MAX_CHARS = 500
_DEFAULT_OVERLAP = 50


def chunk_text(
    text: str, max_chars: int = _DEFAULT_MAX_CHARS, overlap: int = _DEFAULT_OVERLAP
) -> List[str]:
    """按固定长度将长文本切分为带重叠的分块列表。

    保留完整段落尽量不被切断：优先在最近的换行处分界，无换行时按 max_chars 硬切。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # 尝试在 [start, end] 范围内最近换行处切分，避免切断语义单元
        if end < len(text):
            newline = text.rfind("\n", start, end)
            if newline > start:
                end = newline
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def index_document(
    session: Session,
    source_type: str,
    source_name: str,
    text: str,
    knowledge_point: str | None = None,
    meta: dict | None = None,
) -> int:
    """将一份资料分块并向量化入库，返回写入的分块数量。

    文本整体先做一次 embedding 作为该文档语义代表用于检索；
    每个分块分别向量化后逐条入库。
    """
    chunks = chunk_text(text)
    if not chunks:
        return 0

    vectors = embed_texts(chunks)
    for chunk, vec in zip(chunks, vectors):
        session.add(
            KnowledgeChunk(
                source_type=source_type,
                source_name=source_name,
                knowledge_point=knowledge_point,
                content=chunk,
                embedding=vec,
                meta=meta,
            )
        )
    session.commit()
    return len(chunks)

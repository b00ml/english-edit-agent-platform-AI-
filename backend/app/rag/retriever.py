# app/rag/retriever.py —— 知识库向量检索
# 按知识点过滤 + 向量余弦相似度检索最相关分块，供生成时注入上下文。
import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk
from app.rag.embedding import embed_texts

logger = logging.getLogger("app.rag.retriever")


def retrieve(
    session: Session,
    query: str,
    knowledge_point: str | None = None,
    top_k: int = 3,
) -> List[str]:
    """按 query 向量检索最相关的知识分块文本。

    - 若提供 knowledge_point 则先按知识点精确过滤；
    - 否则对全库做余弦相似度检索。
    """
    if not query:
        return []
    vec = embed_texts([query])
    if not vec:
        return []
    qvec = vec[0]

    stmt = (
        select(KnowledgeChunk).order_by(KnowledgeChunk.embedding.cosine_distance(qvec)).limit(top_k)
    )
    if knowledge_point:
        stmt = stmt.where(KnowledgeChunk.knowledge_point == knowledge_point)

    rows = session.execute(stmt).scalars().all()
    return [row.content for row in rows if row.content]


def build_rag_context(
    session: Session, query: str, knowledge_point: str | None = None, top_k: int = 3
) -> str:
    """检索知识片段并拼接为注入生成提示的参考资料文本（无命中返回空串）。

    fail-open（OPT-025）：RAG 是生成质量的增强而非必需依赖——向量化/检索失败
    （embedding 端点不可用、无密钥等）时记告警并返回空串，不阻断生成主流程。
    """
    try:
        snippets = retrieve(session, query, knowledge_point, top_k)
    except Exception:  # noqa: BLE001 —— RAG 不可用不应阻断生成
        logger.warning("RAG 检索失败，降级为无知识上下文生成", exc_info=True)
        return ""
    if not snippets:
        return ""
    return "\n\n".join(snippets)

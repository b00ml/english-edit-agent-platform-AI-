# app/rag/embedding.py —— 文本向量化
# 调用 OpenAI 兼容 embedding 端点（阿里云百炼 text-embedding-v3）生成向量。
from typing import List

from openai import OpenAI

from app.config import settings


def _get_openai_client() -> OpenAI:
    """构建 embedding 客户端（可测试缝：单测/集成测试可整体替换本函数）。"""
    return OpenAI(
        base_url=settings.EMBEDDING_API_BASE,
        api_key=settings.EMBEDDING_API_KEY or "sk-placeholder",
        timeout=settings.EMBEDDING_TIMEOUT,
    )


def embed_texts(texts: List[str]) -> List[List[float]]:
    """批量将文本转换为向量（保留输入顺序）。"""
    if not texts:
        return []
    client = _get_openai_client()
    resp = client.embeddings.create(
        model=settings.EMBEDDING_MODEL_NAME,
        input=texts,
    )
    # 按输入顺序对齐返回的向量
    ordered = [None] * len(texts)
    for item in resp.data:
        ordered[item.index] = item.embedding
    return [vec for vec in ordered if vec is not None]

"""
Knowledge Service Layer
负责知识库上传、索引、检索的业务逻辑
"""

from typing import Optional

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import KnowledgeChunk, User
from app.rag.indexer import index_document
from app.rag.parser import UnsupportedFileTypeError, parse_file
from app.rag.retriever import retrieve as rag_retrieve
from app.repositories.knowledge_repository import KnowledgeRepository


class KnowledgeService:
    """知识库服务"""

    def __init__(self, db: Session):
        self.db = db
        self.knowledge_repo = KnowledgeRepository(db)

    def upload_text(
        self,
        text: str,
        source_type: str,
        source_name: str,
        knowledge_point: Optional[str],
        meta: Optional[dict],
        user: User,
    ) -> dict:
        """
        上传文本并分块索引

        Args:
            text: 原始文本
            source_type: 资料类型（教材/课标/真题）
            source_name: 资料名称
            knowledge_point: 知识点标签
            meta: 额外元数据
            user: 当前用户（用于租户隔离）

        Returns:
            {"chunks": int, "source_type": str, "source_name": str, "knowledge_point": str}
        """
        if not text.strip():
            raise ValidationError("文本内容不能为空")

        chunks = index_document(
            self.db,
            source_type=source_type,
            source_name=source_name,
            text=text,
            knowledge_point=knowledge_point,
            meta=meta,
        )

        if chunks == 0:
            raise ValidationError("分块失败，文本可能为空或过短")

        return {
            "chunks": chunks,
            "source_type": source_type,
            "source_name": source_name,
            "knowledge_point": knowledge_point,
        }

    def upload_file(
        self,
        filename: str,
        content: bytes,
        source_type: str,
        knowledge_point: Optional[str],
        user: User,
    ) -> dict:
        """
        上传文件并解析、分块索引

        Args:
            filename: 文件名
            content: 文件二进制内容
            source_type: 资料类型
            knowledge_point: 知识点标签
            user: 当前用户

        Returns:
            {"chunks": int, "source_type": str, "source_name": str}

        Raises:
            ValidationError: 文件为空/过大
            UnsupportedFileTypeError: 文件类型不支持
        """
        if not filename:
            raise ValidationError("文件名不能为空")

        if len(content) == 0:
            raise ValidationError("文件内容为空")

        MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValidationError("文件过大（上限 10MB）")

        # 解析文件
        try:
            text = parse_file(filename, content)
        except UnsupportedFileTypeError as e:
            raise ValidationError(str(e)) from e
        except ImportError as e:
            raise ValidationError(str(e)) from e

        # 提取文件名（去扩展名）作为 source_name
        import os

        source_name = os.path.splitext(filename)[0]

        # 索引文档
        chunks = index_document(
            self.db,
            source_type=source_type,
            source_name=source_name,
            text=text,
            knowledge_point=knowledge_point,
            meta={"filename": filename},
        )

        if chunks == 0:
            raise ValidationError("分块失败，文件内容可能过短")

        return {
            "chunks": chunks,
            "source_type": source_type,
            "source_name": source_name,
            "knowledge_point": knowledge_point,
        }

    def list_knowledge(
        self, source_type: Optional[str], page: int, page_size: int, user: User
    ) -> dict:
        """
        列出知识分块（分页）

        Args:
            source_type: 可选的资料类型过滤
            page: 页码（从1开始）
            page_size: 每页大小
            user: 当前用户

        Returns:
            {"total": int, "items": list[KnowledgeChunkOut]}
        """
        stmt = select(KnowledgeChunk)
        if source_type:
            stmt = stmt.where(KnowledgeChunk.source_type == source_type)

        total = self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0

        rows = (
            self.db.execute(
                stmt.order_by(KnowledgeChunk.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )

        return {
            "total": total,
            "items": rows,
        }

    def delete_knowledge(self, chunk_id: str, user: User) -> dict:
        """
        删除知识分块

        Args:
            chunk_id: 分块ID
            user: 当前用户

        Returns:
            {"deleted": chunk_id}
        """
        row = self.db.get(KnowledgeChunk, chunk_id)
        if not row:
            raise NotFoundError("分块不存在")

        self.db.delete(row)
        self.db.commit()

        return {"deleted": chunk_id}

    def retrieve_knowledge(
        self, query: str, knowledge_point: Optional[str], top_k: int, user: User
    ) -> dict:
        """
        向量检索知识分块

        Args:
            query: 查询文本
            knowledge_point: 可选的知识点过滤
            top_k: 返回数量
            user: 当前用户

        Returns:
            {"query": str, "snippets": list[dict]}
        """
        snippets = rag_retrieve(self.db, query=query, knowledge_point=knowledge_point, top_k=top_k)

        return {
            "query": query,
            "snippets": snippets,
        }

    def create_chunk(
        self,
        text: str,
        source: str,
        metadata: Optional[dict],
        embedding: Optional[list[float]],
        user: User,
    ) -> dict:
        """
        创建知识库 chunk（低级API，通常不直接调用）

        租户隔离：自动关联 user.tenant_id
        """
        chunk = self.knowledge_repo.create(
            text=text,
            source=source,
            metadata=metadata or {},
            embedding=embedding,
            tenant_id=user.tenant_id,
        )
        self.db.commit()
        self.db.refresh(chunk)

        return {
            "id": chunk.id,
            "text": chunk.text,
            "source": chunk.source,
            "metadata": chunk.metadata,
            "created_at": chunk.created_at.isoformat(),
        }

    def list_chunks(self, user: User, skip: int = 0, limit: int = 50) -> dict:
        """
        列出知识库 chunks（低级API）

        租户隔离：按 user.tenant_id 过滤
        """
        chunks = self.knowledge_repo.list_by_tenant(
            tenant_id=user.tenant_id, skip=skip, limit=limit
        )

        total = self.knowledge_repo.count_by_tenant(tenant_id=user.tenant_id)

        items = []
        for chunk in chunks:
            items.append(
                {
                    "id": chunk.id,
                    "text": chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,
                    "source": chunk.source,
                    "metadata": chunk.metadata,
                    "created_at": chunk.created_at.isoformat(),
                }
            )

        return {"items": items, "total": total, "skip": skip, "limit": limit}

    def delete_chunk(self, chunk_id: str, user: User) -> None:
        """
        删除知识库 chunk（低级API）

        租户隔离：验证 chunk 所属 tenant
        """
        chunk = self.knowledge_repo.get_by_id(chunk_id)

        if not chunk:
            raise NotFoundError(f"Chunk not found: {chunk_id}")

        # 租户隔离校验
        if chunk.tenant_id != user.tenant_id:
            from app.errors import TenantScopeDeniedError

            raise TenantScopeDeniedError("Cannot delete chunk from another tenant")

        self.knowledge_repo.delete(chunk)
        self.db.commit()

    def retrieve(self, query: str, user: User, top_k: int = 5) -> list[dict]:
        """
        向量检索（低级API）

        租户隔离：仅检索 user.tenant_id 的 chunks
        """
        # 这里简化实现，实际需要调用 embedding + pgvector 检索
        # 当前返回最近的 top_k 条（简化逻辑）
        chunks = self.knowledge_repo.list_by_tenant(tenant_id=user.tenant_id, skip=0, limit=top_k)

        results = []
        for chunk in chunks:
            results.append(
                {
                    "id": chunk.id,
                    "text": chunk.text,
                    "source": chunk.source,
                    "metadata": chunk.metadata,
                    "score": 0.9,  # 占位符，实际应计算向量相似度
                }
            )

        return results

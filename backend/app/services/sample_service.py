"""
Sample Service Layer
负责高质量样本沉淀的业务逻辑
"""

from typing import Optional

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import ContentItem, SamplePool, User
from app.repositories.sample_repository import SampleRepository
from app.sample_pool import list_samples as _list_samples
from app.sample_pool import pool_item as _pool_item
from app.sample_pool import remove_sample as _remove_sample
from app.sample_pool import sync_eligible as _sync_eligible


class SampleService:
    """样本池服务"""

    def __init__(self, db: Session):
        self.db = db
        self.sample_repo = SampleRepository(db)

    def create_sample_from_content(
        self, content_id: str, source: str, purpose: str, user: User
    ) -> dict:
        """
        将高质量内容沉淀为回流样本

        Args:
            content_id: 内容ID
            source: 来源标签（manual/auto）
            purpose: 用途（sft/few-shot）
            user: 当前用户

        Returns:
            SamplePool 对象（作为字典）
        """
        item = self.db.get(ContentItem, content_id)
        if item is None:
            raise NotFoundError("内容不存在")

        if item.status not in ("passed", "published"):
            raise ValidationError("仅人工通过或已发布的内容可沉淀为样本")

        sample = _pool_item(self.db, item, source=source, purpose=purpose)
        return sample

    def sync_samples(self, user: User) -> dict:
        """
        自动同步所有高质量内容为样本

        Returns:
            {"added": int, "total": int}
        """
        added = _sync_eligible(self.db)
        total = self.db.query(func.count(SamplePool.id)).scalar() or 0
        return {"added": added, "total": total}

    def list_samples_filtered(
        self,
        template_id: Optional[str],
        knowledge_point: Optional[str],
        purpose: Optional[str],
        source: Optional[str],
        page: int,
        page_size: int,
        user: User,
    ) -> tuple[list[SamplePool], int]:
        """
        检索样本（按条件过滤，分页）

        Returns:
            (rows: list[SamplePool], total: int)
        """
        rows, total = _list_samples(
            self.db,
            template_id=template_id,
            knowledge_point=knowledge_point,
            purpose=purpose,
            source=source,
            page=page,
            page_size=page_size,
        )
        return rows, total

    def export_samples_jsonl(
        self,
        template_id: Optional[str],
        knowledge_point: Optional[str],
        purpose: Optional[str],
        source: Optional[str],
        user: User,
    ) -> list[dict]:
        """
        导出样本为 JSONL 格式数据

        Returns:
            list[dict]: 每条样本的字典
        """
        rows, _ = _list_samples(
            self.db,
            template_id=template_id,
            knowledge_point=knowledge_point,
            purpose=purpose,
            source=source,
            page=1,
            page_size=100000,  # 全量导出
        )

        lines = []
        for s in rows:
            lines.append(
                {
                    "template_id": s.template_id,
                    "knowledge_point": s.knowledge_point,
                    "purpose": s.purpose,
                    "source": s.source,
                    "payload": s.payload,
                    "meta": s.meta,
                }
            )

        return lines

    def delete_sample_by_id(self, sample_id: str, user: User) -> dict:
        """
        删除样本

        Returns:
            {"deleted": sample_id}
        """
        if not _remove_sample(self.db, sample_id):
            raise NotFoundError("样本不存在")

        return {"deleted": sample_id}

    # 以下为旧版租户隔离方法（保留兼容性）

    def create_sample(
        self,
        content_id: str,
        template_id: str,
        quality_score: float,
        metadata: Optional[dict],
        user: User,
    ) -> dict:
        """
        沉淀高质量样本（低级API）

        租户隔离：自动关联 user.tenant_id
        """
        sample = self.sample_repo.create(
            content_id=content_id,
            template_id=template_id,
            quality_score=quality_score,
            metadata=metadata or {},
            tenant_id=user.tenant_id,
        )
        self.db.commit()
        self.db.refresh(sample)

        return {
            "id": sample.id,
            "content_id": sample.content_id,
            "template_id": sample.template_id,
            "quality_score": sample.quality_score,
            "metadata": sample.metadata,
            "created_at": sample.created_at.isoformat(),
        }

    def list_samples(
        self,
        user: User,
        template_id: Optional[str] = None,
        min_score: Optional[float] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict:
        """
        列出样本池（低级API）

        租户隔离：按 user.tenant_id 过滤
        """
        samples = self.sample_repo.list_by_tenant(
            tenant_id=user.tenant_id,
            template_id=template_id,
            min_score=min_score,
            skip=skip,
            limit=limit,
        )

        total = self.sample_repo.count_by_tenant(
            tenant_id=user.tenant_id, template_id=template_id, min_score=min_score
        )

        items = []
        for sample in samples:
            items.append(
                {
                    "id": sample.id,
                    "content_id": sample.content_id,
                    "template_id": sample.template_id,
                    "quality_score": sample.quality_score,
                    "metadata": sample.metadata,
                    "created_at": sample.created_at.isoformat(),
                }
            )

        return {"items": items, "total": total, "skip": skip, "limit": limit}

    def delete_sample(self, sample_id: str, user: User) -> None:
        """
        删除样本（低级API）

        租户隔离：验证 sample 所属 tenant
        """
        sample = self.sample_repo.get_by_id(sample_id)

        if not sample:
            raise NotFoundError(f"Sample not found: {sample_id}")

        # 租户隔离校验
        if sample.tenant_id != user.tenant_id:
            from app.errors import TenantScopeDeniedError

            raise TenantScopeDeniedError("Cannot delete sample from another tenant")

        self.sample_repo.delete(sample)
        self.db.commit()

    def sync_from_content(self, user: User, min_score: float = 0.8) -> dict:
        """
        从 ContentItem 同步高质量样本（低级API）

        租户隔离：仅同步 user.tenant_id 的内容
        """
        synced_count = self.sample_repo.sync_from_content(
            tenant_id=user.tenant_id, min_score=min_score
        )
        self.db.commit()

        return {"synced_count": synced_count, "min_score": min_score}

    def export_samples(self, user: User, template_id: Optional[str] = None) -> list[dict]:
        """
        导出样本数据（低级API，用于训练/评估）

        租户隔离：按 user.tenant_id 过滤
        """
        samples = self.sample_repo.list_by_tenant(
            tenant_id=user.tenant_id, template_id=template_id, skip=0, limit=10000  # 导出全量
        )

        results = []
        for sample in samples:
            results.append(
                {
                    "id": sample.id,
                    "content_id": sample.content_id,
                    "template_id": sample.template_id,
                    "quality_score": sample.quality_score,
                    "metadata": sample.metadata,
                    "created_at": sample.created_at.isoformat(),
                }
            )

        return results

"""
样本池 Repository
职责：SamplePool 数据访问、高质量样本检索
"""

from typing import List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models import SamplePool
from app.repositories.base import BaseRepository


class SampleRepository(BaseRepository[SamplePool]):
    """样本池数据访问层。"""

    def __init__(self, db: Session):
        super().__init__(SamplePool, db)

    def get_by_item(self, item_id: str) -> Optional[SamplePool]:
        """根据内容 ID 查询样本（去重检查）。"""
        return self.db.query(SamplePool).filter(SamplePool.item_id == item_id).first()

    def list_by_template(
        self, template_id: str, skip: int = 0, limit: int = 50
    ) -> List[SamplePool]:
        """按题型查询样本。"""
        return (
            self.db.query(SamplePool)
            .filter(SamplePool.template_id == template_id)
            .order_by(desc(SamplePool.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_purpose(self, purpose: str, skip: int = 0, limit: int = 50) -> List[SamplePool]:
        """按用途查询样本（fewshot/sft）。"""
        return (
            self.db.query(SamplePool)
            .filter(SamplePool.purpose == purpose)
            .order_by(desc(SamplePool.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_source(self, source: str, skip: int = 0, limit: int = 50) -> List[SamplePool]:
        """按来源查询样本（manual/auto）。"""
        return (
            self.db.query(SamplePool)
            .filter(SamplePool.source == source)
            .order_by(desc(SamplePool.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_knowledge_point(
        self, knowledge_point: str, skip: int = 0, limit: int = 50
    ) -> List[SamplePool]:
        """按知识点查询样本。"""
        return (
            self.db.query(SamplePool)
            .filter(SamplePool.knowledge_point == knowledge_point)
            .order_by(desc(SamplePool.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_tenant(self, tenant_id: str, skip: int = 0, limit: int = 50) -> List[SamplePool]:
        """按租户查询样本。"""
        return (
            self.db.query(SamplePool)
            .filter(SamplePool.tenant_id == tenant_id)
            .order_by(desc(SamplePool.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_fewshot_samples(
        self, template_id: str, knowledge_point: Optional[str] = None, limit: int = 3
    ) -> List[SamplePool]:
        """获取 few-shot 样本（按题型 + 知识点过滤）。"""
        query = self.db.query(SamplePool).filter(
            SamplePool.template_id == template_id,
            SamplePool.purpose == "fewshot",
        )
        if knowledge_point:
            query = query.filter(SamplePool.knowledge_point == knowledge_point)
        return query.order_by(desc(SamplePool.created_at)).limit(limit).all()

    def count_by_template(self, template_id: str) -> int:
        """统计题型的样本数。"""
        return (
            self.db.query(func.count(SamplePool.id))
            .filter(SamplePool.template_id == template_id)
            .scalar()
        )

    def count_by_purpose(self, purpose: str) -> int:
        """统计指定用途的样本数。"""
        return (
            self.db.query(func.count(SamplePool.id)).filter(SamplePool.purpose == purpose).scalar()
        )

    def count_by_tenant(self, tenant_id: str) -> int:
        """统计租户的样本数。"""
        return (
            self.db.query(func.count(SamplePool.id))
            .filter(SamplePool.tenant_id == tenant_id)
            .scalar()
        )

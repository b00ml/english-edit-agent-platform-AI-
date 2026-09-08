"""
质检 Repository
职责：QualityRecord、QualityCalibration 数据访问
"""

from typing import List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models import QualityCalibration, QualityRecord
from app.repositories.base import BaseRepository


class QualityRecordRepository(BaseRepository[QualityRecord]):
    """质检记录数据访问层。"""

    def __init__(self, db: Session):
        super().__init__(QualityRecord, db)

    def get_by_item(self, item_id: str) -> Optional[QualityRecord]:
        """查询内容的最新质检记录。"""
        return (
            self.db.query(QualityRecord)
            .filter(QualityRecord.item_id == item_id)
            .order_by(desc(QualityRecord.created_at))
            .first()
        )

    def list_by_source(self, source: str, skip: int = 0, limit: int = 50) -> List[QualityRecord]:
        """按来源查询质检记录（auto/manual_review）。"""
        return (
            self.db.query(QualityRecord)
            .filter(QualityRecord.source == source)
            .order_by(desc(QualityRecord.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_tenant(self, tenant_id: str, skip: int = 0, limit: int = 50) -> List[QualityRecord]:
        """按租户查询质检记录。"""
        return (
            self.db.query(QualityRecord)
            .filter(QualityRecord.tenant_id == tenant_id)
            .order_by(desc(QualityRecord.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_manual_rejections(self, skip: int = 0, limit: int = 50) -> List[QualityRecord]:
        """查询人工驳回记录（用于校准分析）。"""
        return (
            self.db.query(QualityRecord)
            .filter(QualityRecord.source == "manual_review")
            .filter(QualityRecord.reason.isnot(None))
            .order_by(desc(QualityRecord.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_by_source(self, source: str) -> int:
        """统计指定来源的质检记录数。"""
        return (
            self.db.query(func.count(QualityRecord.id))
            .filter(QualityRecord.source == source)
            .scalar()
        )


class QualityCalibrationRepository(BaseRepository[QualityCalibration]):
    """质检校准记录数据访问层。"""

    def __init__(self, db: Session):
        super().__init__(QualityCalibration, db)

    def get_latest_by_template(self, template_id: str) -> Optional[QualityCalibration]:
        """查询题型的最新校准记录（作为当前生效权重）。"""
        return (
            self.db.query(QualityCalibration)
            .filter(QualityCalibration.template_id == template_id)
            .order_by(desc(QualityCalibration.created_at))
            .first()
        )

    def list_by_template(
        self, template_id: str, skip: int = 0, limit: int = 20
    ) -> List[QualityCalibration]:
        """查询题型的历史校准记录。"""
        return (
            self.db.query(QualityCalibration)
            .filter(QualityCalibration.template_id == template_id)
            .order_by(desc(QualityCalibration.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_tenant(
        self, tenant_id: str, skip: int = 0, limit: int = 50
    ) -> List[QualityCalibration]:
        """按租户查询校准记录。"""
        return (
            self.db.query(QualityCalibration)
            .filter(QualityCalibration.tenant_id == tenant_id)
            .order_by(desc(QualityCalibration.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_by_template(self, template_id: str) -> int:
        """统计题型的校准次数。"""
        return (
            self.db.query(func.count(QualityCalibration.id))
            .filter(QualityCalibration.template_id == template_id)
            .scalar()
        )

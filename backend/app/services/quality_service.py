"""
质检 Service
职责：质检标注、校准、质检记录查询
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.calibration import recalibrate
from app.engine.agreement import judge_vs_manual
from app.models import ContentItem, QualityCalibration, QualityRecord, QuestionTemplate, User
from app.repositories import QualityCalibrationRepository, QualityRecordRepository
from app.schemas import CalibrateRequest, CalibrationOut, QualityReviewRequest
from app.versioning import quality_snapshot
from app.workflow.graph import resume_human_review


class QualityService:
    """质检业务逻辑层。"""

    def __init__(self, db: Session):
        self.db = db
        self.quality_repo = QualityRecordRepository(db)
        self.calibration_repo = QualityCalibrationRepository(db)

    def review_content(
        self, content_id: str, req: QualityReviewRequest, current_user: User
    ) -> QualityRecord:
        """人工质检标注（通过/驳回）。

        灰区人工卡点（P1-1）：条目若由 LangGraph interrupt 暂停（thread_id 存在且
        status=awaiting_review），凭 Command(resume) 恢复图，由 human_review 节点
        完成裁决落库；存量条目走旧路径。

        Args:
            content_id: 内容 ID
            req: 质检请求（通过/驳回 + 原因）
            current_user: 当前用户（记录评审人）

        Returns:
            质检记录

        Raises:
            HTTPException: 内容不存在
        """
        item = self.db.get(ContentItem, content_id)
        if item is None:
            raise HTTPException(status_code=404, detail="内容不存在")

        # 通过/驳回的评分约定：通过=100，驳回=0
        score = 100.0 if req.pass_ else 0.0

        # 若条目处于灰区卡点状态，通过 LangGraph 恢复执行
        if item.thread_id and item.status == "awaiting_review":
            resume_human_review(
                item.thread_id,
                {
                    "approved": req.pass_,
                    "score": score,
                    "reason": req.reason or "",
                    "reviewer_id": current_user.id,
                },
                self.db,
            )
            # 查询 human_review 节点创建的质检记录
            record = (
                self.db.query(QualityRecord)
                .filter(QualityRecord.item_id == content_id)
                .filter(QualityRecord.source == "manual_review")
                .order_by(desc(QualityRecord.created_at))
                .first()
            )
            return record

        # 存量条目走旧路径：直接创建质检记录
        template = (
            self.db.query(QuestionTemplate)
            .filter(QuestionTemplate.type_id == item.template_id)
            .first()
        )
        record = self.quality_repo.create(
            item_id=content_id,
            score=score,
            dimension_scores={"manual": score},
            source="manual_review",
            reviewer=current_user.id,
            reason=req.reason if not req.pass_ else None,
            tenant_id=current_user.tenant_id,
            template_version=template.version if template else None,
            config_snapshot=(quality_snapshot(template, model_name=None) if template else None),
        )

        # 同步更新内容状态
        item.status = "passed" if req.pass_ else "rejected"
        item.qc_score = score
        self.db.commit()
        self.db.refresh(record)
        return record

    def calibrate_quality(self, req: CalibrateRequest) -> CalibrationOut:
        """触发质检权重校准。

        用人工驳回样本反向校准 judge 维度权重：
        - 收集假阳性样本（auto 高分但 manual 驳回）
        - 计算放水度（假阳性集维度分 - 通过集维度分）
        - 下调放水维度权重

        Args:
            req: 校准请求（题型 + 超参）

        Returns:
            校准结果（新权重 + 放水度 + 样本统计）
        """
        calib = recalibrate(
            self.db,
            req.template_id,
            alpha=req.alpha,
            min_samples=req.min_samples,
            min_fp=req.min_fp,
        )

        # 附带：本次校准样本集上 judge 与人工的二值判定一致性（P0-4，只读参考）
        pairs = self._auto_manual_pairs(req.template_id)
        out = CalibrationOut.model_validate(calib)
        out.agreement = judge_vs_manual(pairs, calib.threshold)
        return out

    def list_calibrations(
        self, template_id: str, skip: int = 0, limit: int = 20
    ) -> list[QualityCalibration]:
        """查询题型的历史校准记录。"""
        return self.calibration_repo.list_by_template(template_id, skip, limit)

    def get_latest_calibration(self, template_id: str) -> Optional[QualityCalibration]:
        """获取题型的最新校准记录（当前生效权重）。"""
        return self.calibration_repo.get_latest_by_template(template_id)

    def get_quality_record(self, content_id: str) -> Optional[QualityRecord]:
        """查询内容的最新质检记录。"""
        return self.quality_repo.get_by_item(content_id)

    def list_manual_rejections(self, skip: int = 0, limit: int = 50) -> list[QualityRecord]:
        """查询人工驳回记录（用于校准分析）。"""
        return self.quality_repo.list_manual_rejections(skip, limit)

    def _auto_manual_pairs(self, template_id: str) -> list:
        """收集同 item 的 (auto 总分, manual 分) 标注对（各取该 item 的第一条）。"""
        rows = (
            self.db.query(QualityRecord.item_id, QualityRecord.source, QualityRecord.score)
            .join(ContentItem, ContentItem.id == QualityRecord.item_id)
            .filter(ContentItem.template_id == template_id)
            .filter(QualityRecord.source.in_(["auto", "manual_review"]))
            .order_by(QualityRecord.item_id, QualityRecord.created_at)
            .all()
        )
        auto: dict = {}
        manual: dict = {}
        for item_id, source, score in rows:
            if source == "auto":
                auto.setdefault(item_id, float(score))
            else:
                manual.setdefault(item_id, float(score))

        # 返回同时有 auto 和 manual 的样本对
        common_ids = set(auto.keys()) & set(manual.keys())
        return [(auto[iid], manual[iid]) for iid in common_ids]

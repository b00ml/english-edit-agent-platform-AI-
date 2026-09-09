"""
链路追踪 Repository
职责：TraceLog 数据访问、成本统计
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models import TraceLog
from app.repositories.base import BaseRepository


class TraceRepository(BaseRepository[TraceLog]):
    """链路追踪数据访问层。"""

    def __init__(self, db: Session):
        super().__init__(TraceLog, db)

    def get_by_trace_id(self, trace_id: str) -> Optional[TraceLog]:
        """根据 trace_id 查询单条记录。"""
        return self.db.query(TraceLog).filter(TraceLog.trace_id == trace_id).first()

    def list_by_task(self, task_id: str, skip: int = 0, limit: int = 100) -> List[TraceLog]:
        """查询任务的所有调用记录。"""
        return (
            self.db.query(TraceLog)
            .filter(TraceLog.task_id == task_id)
            .order_by(TraceLog.created_at)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_item(self, item_id: str, skip: int = 0, limit: int = 50) -> List[TraceLog]:
        """查询内容条目的调用记录。"""
        return (
            self.db.query(TraceLog)
            .filter(TraceLog.item_id == item_id)
            .order_by(TraceLog.created_at)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_template(self, template_id: str, skip: int = 0, limit: int = 100) -> List[TraceLog]:
        """查询题型的调用记录。"""
        return (
            self.db.query(TraceLog)
            .filter(TraceLog.template_id == template_id)
            .order_by(desc(TraceLog.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_stage(self, stage: str, skip: int = 0, limit: int = 100) -> List[TraceLog]:
        """按调用阶段查询（generate/qc）。"""
        return (
            self.db.query(TraceLog)
            .filter(TraceLog.stage == stage)
            .order_by(desc(TraceLog.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_tenant(self, tenant_id: str, skip: int = 0, limit: int = 100) -> List[TraceLog]:
        """按租户查询调用记录。"""
        return (
            self.db.query(TraceLog)
            .filter(TraceLog.tenant_id == tenant_id)
            .order_by(desc(TraceLog.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_cost_by_task(self, task_id: str) -> Dict[str, Any]:
        """统计任务的总成本与 token 消耗。"""
        result = (
            self.db.query(
                func.sum(TraceLog.cost).label("total_cost"),
                func.sum(TraceLog.prompt_tokens).label("total_prompt_tokens"),
                func.sum(TraceLog.completion_tokens).label("total_completion_tokens"),
                func.count(TraceLog.id).label("call_count"),
            )
            .filter(TraceLog.task_id == task_id)
            .first()
        )
        return {
            "total_cost": float(result.total_cost or 0),
            "total_prompt_tokens": int(result.total_prompt_tokens or 0),
            "total_completion_tokens": int(result.total_completion_tokens or 0),
            "call_count": int(result.call_count or 0),
        }

    def get_cost_by_template(
        self, template_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        """统计题型在时间段内的成本。"""
        result = (
            self.db.query(
                func.sum(TraceLog.cost).label("total_cost"),
                func.sum(TraceLog.prompt_tokens).label("total_prompt_tokens"),
                func.sum(TraceLog.completion_tokens).label("total_completion_tokens"),
                func.count(TraceLog.id).label("call_count"),
            )
            .filter(TraceLog.template_id == template_id)
            .filter(TraceLog.created_at >= start)
            .filter(TraceLog.created_at < end)
            .first()
        )
        return {
            "total_cost": float(result.total_cost or 0),
            "total_prompt_tokens": int(result.total_prompt_tokens or 0),
            "total_completion_tokens": int(result.total_completion_tokens or 0),
            "call_count": int(result.call_count or 0),
        }

    def get_cost_by_stage(self, task_id: str, stage: str) -> Dict[str, Any]:
        """统计任务中指定阶段的成本（generate/qc）。"""
        result = (
            self.db.query(
                func.sum(TraceLog.cost).label("total_cost"),
                func.sum(TraceLog.prompt_tokens).label("total_prompt_tokens"),
                func.sum(TraceLog.completion_tokens).label("total_completion_tokens"),
                func.count(TraceLog.id).label("call_count"),
            )
            .filter(TraceLog.task_id == task_id)
            .filter(TraceLog.stage == stage)
            .first()
        )
        return {
            "total_cost": float(result.total_cost or 0),
            "total_prompt_tokens": int(result.total_prompt_tokens or 0),
            "total_completion_tokens": int(result.total_completion_tokens or 0),
            "call_count": int(result.call_count or 0),
        }

    def get_success_rate_by_template(self, template_id: str) -> Dict[str, Any]:
        """统计题型的首过率（成功/总调用）。"""
        total = (
            self.db.query(func.count(TraceLog.id))
            .filter(TraceLog.template_id == template_id)
            .scalar()
        )
        success = (
            self.db.query(func.count(TraceLog.id))
            .filter(TraceLog.template_id == template_id)
            .filter(TraceLog.success.is_(True))
            .scalar()
        )
        return {
            "total": int(total or 0),
            "success": int(success or 0),
            "rate": float(success / total) if total > 0 else 0.0,
        }

    def count_by_tenant(self, tenant_id: str) -> int:
        """统计租户的 Trace 总数。"""
        return (
            self.db.query(func.count(TraceLog.id)).filter(TraceLog.tenant_id == tenant_id).scalar()
            or 0
        )

    def sum_cost(self, tenant_id: str, since: Optional[datetime] = None) -> float:
        """统计租户的总成本（可选时间范围）。"""
        query = self.db.query(func.sum(TraceLog.cost)).filter(TraceLog.tenant_id == tenant_id)
        if since:
            query = query.filter(TraceLog.created_at >= since)
        return float(query.scalar() or 0)

    def aggregate_by_model(
        self, tenant_id: str, since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """按模型聚合成本统计。"""
        query = (
            self.db.query(
                TraceLog.model,
                func.sum(TraceLog.cost).label("total_cost"),
                func.sum(TraceLog.prompt_tokens + TraceLog.completion_tokens).label("total_tokens"),
                func.count(TraceLog.id).label("call_count"),
            )
            .filter(TraceLog.tenant_id == tenant_id)
            .group_by(TraceLog.model)
        )
        if since:
            query = query.filter(TraceLog.created_at >= since)

        results = []
        for row in query.all():
            results.append(
                {
                    "model": row.model,
                    "total_cost": float(row.total_cost or 0),
                    "total_tokens": int(row.total_tokens or 0),
                    "call_count": int(row.call_count or 0),
                }
            )
        return results

    def aggregate_by_date(
        self, tenant_id: str, since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """按日期聚合成本统计。"""
        query = (
            self.db.query(
                func.date(TraceLog.created_at).label("date"),
                func.sum(TraceLog.cost).label("total_cost"),
                func.count(TraceLog.id).label("call_count"),
            )
            .filter(TraceLog.tenant_id == tenant_id)
            .group_by(func.date(TraceLog.created_at))
            .order_by(func.date(TraceLog.created_at))
        )
        if since:
            query = query.filter(TraceLog.created_at >= since)

        results = []
        for row in query.all():
            results.append(
                {
                    "date": row.date.isoformat() if row.date else None,
                    "total_cost": float(row.total_cost or 0),
                    "call_count": int(row.call_count or 0),
                }
            )
        return results

    def structured_output_stats(self, tenant_id: str) -> Dict[str, Any]:
        """结构化输出统计（成功率/重试率/模型分布）。"""
        # 总调用数
        total = (
            self.db.query(func.count(TraceLog.id))
            .filter(TraceLog.tenant_id == tenant_id)
            .filter(TraceLog.stage == "generate")  # 只统计生成阶段
            .scalar()
            or 0
        )

        # 成功数（success=True）
        success = (
            self.db.query(func.count(TraceLog.id))
            .filter(TraceLog.tenant_id == tenant_id)
            .filter(TraceLog.stage == "generate")
            .filter(TraceLog.success.is_(True))
            .scalar()
            or 0
        )

        # 重试数：失败尝试以 success=False 落库；TraceLog 没有独立 error 列。
        retry = (
            self.db.query(func.count(TraceLog.id))
            .filter(TraceLog.tenant_id == tenant_id)
            .filter(TraceLog.stage == "generate")
            .filter(TraceLog.success.is_(False))
            .scalar()
            or 0
        )

        # 按模型分布
        by_model = (
            self.db.query(TraceLog.model, func.count(TraceLog.id).label("count"))
            .filter(TraceLog.tenant_id == tenant_id)
            .filter(TraceLog.stage == "generate")
            .group_by(TraceLog.model)
            .all()
        )

        return {
            "total": int(total),
            "success_rate": float(success / total) if total > 0 else 0.0,
            "retry_rate": float(retry / total) if total > 0 else 0.0,
            "by_model": [{"model": row.model, "count": int(row.count)} for row in by_model],
        }

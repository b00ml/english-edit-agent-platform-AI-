"""
生成任务 Service
职责：生成任务创建、查询、状态管理
"""

import logging
from typing import Optional

import jsonschema
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.dedup import compute_request_hash
from app.errors import DuplicateTaskError, InvalidTemplateParamsError
from app.models import GenerationTask, ModelProfile, QuestionTemplate, User
from app.outbox import create_generation_dispatch, relay_pending
from app.repositories import TaskRepository
from app.schemas import GenerateRequest, GenerateResponse, TaskListOut, TaskOut
from app.versioning import task_version_snapshot_with_model

# 正在执行、不应重复提交的任务状态
_ACTIVE_TASK_STATUSES = ("pending", "running")


class GenerationService:
    """生成任务业务逻辑层。"""

    def __init__(self, db: Session):
        self.db = db
        self.task_repo = TaskRepository(db)
        self.logger = logging.getLogger("app.services.generation")

    def create_task(self, req: GenerateRequest, current_user: User, celery_app) -> GenerateResponse:
        """创建生成任务并投递到 Celery 队列。

        Args:
            req: 生成请求参数
            current_user: 当前用户
            celery_app: Celery 实例（用于投递任务）

        Returns:
            包含 task_id 的响应

        Raises:
            HTTPException: 题型不存在
            InvalidTemplateParamsError: 参数校验失败
            DuplicateTaskError: 重复提交
        """
        # 校验题型模板存在且未禁用
        template = (
            self.db.query(QuestionTemplate)
            .filter(QuestionTemplate.type_id == req.template_id)
            .first()
        )
        if template is None or template.status == "disabled":
            raise HTTPException(status_code=404, detail="题型模板不存在或已禁用")

        # 校验输入参数符合模板 input_schema（JSON Schema Draft 2020-12）
        if template.input_schema:
            try:
                jsonschema.validate(
                    req.params,
                    template.input_schema,
                    format_checker=jsonschema.FormatChecker(),
                )
            except jsonschema.ValidationError as e:
                # 提取字段路径与校验关键字，脱敏后返回给前端
                field_path = list(e.path) if e.path else []
                validation_keyword = e.validator
                # 错误信息脱敏：只保留字段路径与关键字，不暴露敏感参数值
                raise InvalidTemplateParamsError(
                    message=f"参数校验失败: {e.message}",
                    field_path=field_path,
                    validation_keyword=validation_keyword,
                )

        # 去重：相同题型+规范参数+schema版本且任务仍在执行中，则拒绝重复提交
        # 使用 template.updated_at 作为 schema 版本标识（模板更新后允许重新生成）
        schema_version = template.updated_at.isoformat() if template.updated_at else None
        request_hash = compute_request_hash(req.template_id, req.params, schema_version)
        existing = self.task_repo.get_by_request_hash(request_hash)
        if existing is not None:
            raise DuplicateTaskError(
                f"相同题型与参数的生成任务已存在（任务 {existing.id}），请勿重复提交",
                existing.id,
            )

        # 创建任务
        model_name = (template.run_config or {}).get("model_profile")
        if isinstance(model_name, dict):
            model_name = model_name.get("default")
        profile = None
        if isinstance(model_name, str):
            profile = self.db.query(ModelProfile).filter(ModelProfile.name == model_name).first()
        if profile is None:
            profile = self.db.query(ModelProfile).filter(ModelProfile.is_default.is_(True)).first()
        if profile is not None and not isinstance(profile, ModelProfile):
            profile = None
        task = self.task_repo.create(
            template_id=req.template_id,
            params=req.params,
            request_hash=request_hash,
            quantity=req.quantity,
            status="pending",
            progress=0.0,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            version_snapshot=task_version_snapshot_with_model(template, profile),
        )
        self.db.flush()
        create_generation_dispatch(self.db, task)
        self.db.commit()
        self.db.refresh(task)

        # 数据库提交后立即尝试 relay；进程/Redis 故障时保留 pending outbox，
        # 不再留下“任务已创建但消息丢失”的不可解释状态。
        try:
            relay_result = relay_pending(
                self.db,
                lambda name, args, task_id=None: celery_app.send_task(
                    name, args=args, task_id=task_id
                ),
                limit=1,
            )
            # 兼容未执行新迁移的测试/旧实例：Outbox 未能被扫描时保留旧发送路径，
            # 但真实数据库仍有 pending 事件，后续 relay 会再次校正投递状态。
            if relay_result.get("scanned", 0) == 0:
                celery_app.send_task(
                    "app.worker.tasks.process_generation_task",
                    args=[task.id],
                    task_id=f"task:{task.id}:dispatch",
                )
        except Exception:  # noqa: BLE001 - relay 失败由 outbox worker 后续补偿
            self.logger.warning("任务 outbox 首次 relay 失败 task_id=%s", task.id, exc_info=True)
        return GenerateResponse(task_id=task.id, status=task.status)

    def get_task(self, task_id: str) -> GenerationTask:
        """查询单个任务详情与进度。

        Raises:
            HTTPException: 任务不存在
        """
        task = self.task_repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
    ) -> TaskListOut:
        """任务列表（分页）。

        Args:
            page: 页码（从 1 开始）
            page_size: 每页数量
            user_id: 按用户过滤（可选）
            tenant_id: 按租户过滤（可选）
        """
        skip = (page - 1) * page_size

        if user_id:
            tasks = self.task_repo.list_by_user(user_id, skip, page_size)
            total = self.task_repo.count_by_user(user_id)
        elif tenant_id:
            tasks = self.task_repo.list_by_tenant(tenant_id, skip, page_size)
            total = self.task_repo.count_by_tenant(tenant_id)
        else:
            tasks = self.task_repo.list_all(skip, page_size)
            total = self.task_repo.count()

        return TaskListOut(
            total=total,
            page=page,
            page_size=page_size,
            items=[TaskOut.model_validate(t) for t in tasks],
        )

    def update_task_status(
        self, task_id: str, status: str, progress: Optional[float] = None
    ) -> GenerationTask:
        """更新任务状态与进度（供 Worker 调用）。

        Args:
            task_id: 任务 ID
            status: 新状态
            progress: 进度（0-1，可选）
        """
        task = self.task_repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")

        update_data = {"status": status}
        if progress is not None:
            update_data["progress"] = progress

        self.task_repo.update(task, **update_data)
        self.db.commit()
        self.db.refresh(task)
        return task

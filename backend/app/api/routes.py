# app/api/routes.py —— FastAPI 业务接口
import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.calibration import (
    list_calibrations,
    recalibrate,
)
from app.config import settings
from app.database import get_db
from app.dedup import compute_request_hash
from app.engine.agreement import judge_vs_manual
from app.engine.metrics import compute_structured_stats
from app.errors import DuplicateTaskError
from app.models import (
    AppNotification,
    ContentItem,
    GenerationTask,
    KnowledgeChunk,
    ModelProfile,
    QualityRecord,
    QuestionTemplate,
    SamplePool,
    TraceLog,
    User,
)
from app.notification import notify_content_rejected
from app.rag.indexer import index_document
from app.rag.parser import UnsupportedFileTypeError, parse_file
from app.rag.retriever import retrieve
from app.sample_pool import (
    list_samples,
    pool_item,
    remove_sample,
    sync_eligible,
)
from app.schemas import (
    CalibrateRequest,
    CalibrationOut,
    ContentListOut,
    ContentOut,
    CostByKeyOut,
    CostDeepOut,
    CostOut,
    CostStageOut,
    CostTraceOut,
    DashboardKpi,
    DashboardOut,
    GenerateRequest,
    GenerateResponse,
    HealthOut,
    KnowledgeChunkOut,
    KnowledgeListOut,
    KnowledgeRetrieveOut,
    KnowledgeUploadIn,
    KnowledgeUploadOut,
    LoginIn,
    LoginOut,
    ModelProfileIn,
    ModelProfileOut,
    NotificationListOut,
    NotificationOut,
    QualityOut,
    QualityReviewRequest,
    SamplePoolIn,
    SamplePoolListOut,
    SamplePoolOut,
    SampleSyncOut,
    StructuredStatsOut,
    TaskListOut,
    TaskOut,
    TemplateOut,
    TraceListOut,
    TraceOut,
    TraceSummaryOut,
    UnreadCountOut,
    UserCreateIn,
    UserListOut,
    UserOut,
    UserUpdateIn,
)
from app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_permission,
    verify_password,
)
from app.worker.celery_app import celery_app
from app.workflow.graph import resume_human_review

router = APIRouter()


# 正在执行、不应重复提交的任务状态
_ACTIVE_TASK_STATUSES = ("pending", "running")


# ---------------------------------------------------------------------------
# 认证（登录 / 当前用户）
# ---------------------------------------------------------------------------
@router.post("/api/auth/login", response_model=LoginOut)
def login(req: LoginIn, db: Session = Depends(get_db)):
    """用户登录：校验用户名密码，成功签发 JWT。"""
    user = db.query(User).filter(User.username == req.username).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=401, detail="账号已被禁用")
    return LoginOut(access_token=create_access_token(user), user=user)


@router.get("/api/auth/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    """返回当前登录用户信息。"""
    return user


# ---------------------------------------------------------------------------
# 用户管理（仅管理员）
# ---------------------------------------------------------------------------
@router.get("/api/users", response_model=UserListOut)
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user:manage")),
):
    """用户列表（分页），仅管理员可访问。"""
    total = db.query(func.count(User.id)).scalar() or 0
    users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return UserListOut(total=total, items=users)


@router.post("/api/users", response_model=UserOut)
def create_user(
    req: UserCreateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user:manage")),
):
    """创建用户（管理员）。用户名唯一，密码 bcrypt 哈希入库。"""
    if db.query(User).filter(User.username == req.username).first() is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        display_name=req.display_name or req.username,
        role=req.role,
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/api/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    req: UserUpdateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user:manage")),
):
    """更新用户（管理员）：改显示名/角色/密码/状态。"""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.role is not None:
        user.role = req.role
    if req.password is not None:
        user.password_hash = hash_password(req.password)
    if req.status is not None:
        user.status = req.status
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# 发起生成
# ---------------------------------------------------------------------------
@router.post("/api/generate", response_model=GenerateResponse)
def create_generate_task(
    req: GenerateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("generate:create")),
):
    """创建生成任务并投递到 Celery 队列。

    相同题型+参数且仍在执行中的任务会被去重拦截（返回 409）。
    """
    # 校验题型模板存在
    template = (
        db.query(QuestionTemplate).filter(QuestionTemplate.type_id == req.template_id).first()
    )
    if template is None:
        raise HTTPException(status_code=404, detail="题型模板不存在")

    # 去重：相同题型+规范参数且任务仍在执行中，则拒绝重复提交
    request_hash = compute_request_hash(req.template_id, req.params)
    existing = (
        db.query(GenerationTask)
        .filter(
            GenerationTask.request_hash == request_hash,
            GenerationTask.status.in_(_ACTIVE_TASK_STATUSES),
        )
        .first()
    )
    if existing is not None:
        raise DuplicateTaskError(
            f"相同题型与参数的生成任务已存在（任务 {existing.id}），请勿重复提交",
            existing.id,
        )

    task = GenerationTask(
        template_id=req.template_id,
        params=req.params,
        request_hash=request_hash,
        quantity=req.quantity,
        status="pending",
        progress=0.0,
        tenant_id=req.tenant_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 投递到 Celery 队列（异步执行）
    celery_app.send_task(
        "app.worker.tasks.process_generation_task",
        args=[task.id],
    )
    return GenerateResponse(task_id=task.id)


# ---------------------------------------------------------------------------
# 任务查询
# ---------------------------------------------------------------------------
@router.get("/api/tasks/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("content:read")),
):
    """查询单个任务详情与进度。"""
    task = db.get(GenerationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/api/tasks", response_model=TaskListOut)
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("content:read")),
):
    """任务列表（分页）。"""
    total = db.query(func.count(GenerationTask.id)).scalar() or 0
    tasks = (
        db.query(GenerationTask)
        .order_by(GenerationTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return TaskListOut(total=total, items=tasks)


# ---------------------------------------------------------------------------
# 内容检索与操作
# ---------------------------------------------------------------------------
@router.get("/api/contents", response_model=ContentListOut)
def list_contents(
    template_id: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("content:read")),
):
    """内容检索（可按 template_id / status 筛选）。"""
    query = select(ContentItem)
    if template_id:
        query = query.where(ContentItem.template_id == template_id)
    if status:
        query = query.where(ContentItem.status == status)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = (
        db.execute(
            query.order_by(ContentItem.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return ContentListOut(total=total, items=rows)


@router.get("/api/contents/{content_id}", response_model=ContentOut)
def get_content(
    content_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("content:read")),
):
    """内容详情。"""
    item = db.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="内容不存在")
    return item


@router.post("/api/contents/{content_id}/publish", response_model=ContentOut)
def publish_content(
    content_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("content:publish")),
):
    """发布内容。"""
    item = db.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="内容不存在")
    item.status = "published"
    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# 人工质检
# ---------------------------------------------------------------------------
@router.post("/api/quality/{content_id}/review", response_model=QualityOut)
def review_content(
    content_id: str,
    req: QualityReviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("quality:review")),
):
    """人工质检标注：通过/驳回，写入 QualityRecord。

    灰区人工卡点（P1-1）：条目若由 LangGraph interrupt 暂停（thread_id 存在且
    status=awaiting_review），凭 Command(resume) 恢复图，由 human_review 节点
    完成裁决落库；存量条目走旧路径。
    """
    item = db.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="内容不存在")

    # 通过/驳回的评分约定：通过=100，驳回=0
    score = 100.0 if req.pass_ else 0.0

    if item.thread_id and item.status == "awaiting_review":
        resume_human_review(
            item.thread_id,
            {"approved": req.pass_, "score": score, "reason": req.reason or ""},
            db,
        )
        record = (
            db.query(QualityRecord)
            .filter(QualityRecord.item_id == content_id)
            .filter(QualityRecord.source == "manual_review")
            .order_by(QualityRecord.created_at.desc())
            .first()
        )
        return record

    record = QualityRecord(
        item_id=content_id,
        score=score,
        dimension_scores={"manual": score},
        source="manual_review",
        reviewer="human",
        reason=req.reason if not req.pass_ else None,
    )
    db.add(record)

    # 同步更新内容状态
    item.status = "passed" if req.pass_ else "rejected"
    item.qc_score = score
    db.commit()
    db.refresh(record)

    # 驳回时生成站内通知
    if not req.pass_:
        notify_content_rejected(db, item, req.reason)
    return record


# ---------------------------------------------------------------------------
# 质检校准（J1 质量闭环）
# ---------------------------------------------------------------------------
@router.post("/api/quality/calibrate", response_model=CalibrationOut)
def calibrate_quality(
    req: CalibrateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("quality:review")),
):
    """触发质检权重校准：用人工驳回样本反向校准 judge 维度权重。

    闭环：低分自动改版 → 人工驳回记录 → 假阳性样本 → 计算放水度 → 降权。
    样本不足时写入"样本不足"记录但不改变默认权重。
    """
    calib = recalibrate(
        db,
        req.template_id,
        alpha=req.alpha,
        min_samples=req.min_samples,
        min_fp=req.min_fp,
    )
    # 附带：本次校准样本集上 judge 与人工的二值判定一致性（P0-4，只读参考）
    pairs = _auto_manual_pairs(db, req.template_id)
    out = CalibrationOut.model_validate(calib)
    out.agreement = judge_vs_manual(pairs, calib.threshold)
    return out


def _auto_manual_pairs(db: Session, template_id: str) -> list:
    """收集同 item 的 (auto 总分, manual 分) 标注对（各取该 item 的第一条）。"""
    rows = (
        db.query(QualityRecord.item_id, QualityRecord.source, QualityRecord.score)
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
    return [(auto[i], manual[i]) for i in auto if i in manual]


@router.get("/api/quality/calibration", response_model=list[CalibrationOut])
def get_calibrations(
    template_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """查询校准记录列表（可按模板过滤），按时间倒序。"""
    return list_calibrations(db, template_id)


# ---------------------------------------------------------------------------
# 成本聚合
# ---------------------------------------------------------------------------
@router.get("/api/costs", response_model=list[CostOut])
def cost_aggregation(
    group_by: str = Query("template", pattern="^(template|model|task)$"),
    template_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """成本聚合：按 题型/模型/任务 维度归并每条 LLM 调用的成本。

    - group_by=template：按题型（TraceLog.template_id）聚合；
    - group_by=model：按模型聚合；
    - group_by=task：按生成任务（TraceLog.task_id）聚合。
    可选 template_id 过滤。未关联到题型/任务的调用归入 unknown 维度。
    """
    # 统一先关联内容条目（仅用于 template_id 过滤）
    base = db.query(TraceLog, ContentItem.template_id.label("tpl_id")).outerjoin(
        ContentItem, ContentItem.id == TraceLog.item_id
    )
    if template_id:
        base = base.filter(
            (ContentItem.template_id == template_id) | (TraceLog.template_id == template_id)
        )

    if group_by == "task":
        rows = (
            base.with_entities(
                func.coalesce(TraceLog.task_id, "unknown").label("name"),
                func.coalesce(func.sum(TraceLog.cost), 0.0).label("total_cost"),
                func.count(TraceLog.id).label("count"),
            )
            .group_by(TraceLog.task_id)
            .all()
        )
    elif group_by == "model":
        rows = (
            base.with_entities(
                func.coalesce(TraceLog.model, "unknown").label("name"),
                func.coalesce(func.sum(TraceLog.cost), 0.0).label("total_cost"),
                func.count(TraceLog.id).label("count"),
            )
            .group_by(TraceLog.model)
            .all()
        )
    else:  # template
        rows = (
            base.with_entities(
                func.coalesce(TraceLog.template_id, "unknown").label("name"),
                func.coalesce(func.sum(TraceLog.cost), 0.0).label("total_cost"),
                func.count(TraceLog.id).label("count"),
            )
            .group_by(TraceLog.template_id)
            .all()
        )

    return [CostOut(name=r.name, total_cost=float(r.total_cost), count=int(r.count)) for r in rows]


# ---------------------------------------------------------------------------
# 深度成本报表（P3 / K2）
# ---------------------------------------------------------------------------
def _cost_by_key(db: Session, key_col, unknown: str) -> list:
    """按指定列聚合成本与 token（coalesce 归入 unknown 维度）。"""
    rows = (
        db.query(
            func.coalesce(key_col, unknown).label("name"),
            func.count(TraceLog.id).label("count"),
            func.coalesce(func.sum(TraceLog.cost), 0.0).label("total_cost"),
            func.coalesce(func.sum(TraceLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(TraceLog.completion_tokens), 0).label("completion_tokens"),
        )
        .group_by(key_col)
        .order_by(func.sum(TraceLog.cost).desc())
        .all()
    )
    return [
        CostByKeyOut(
            name=r.name,
            count=int(r.count),
            total_cost=float(r.total_cost),
            prompt_tokens=int(r.prompt_tokens),
            completion_tokens=int(r.completion_tokens),
            total_tokens=int(r.prompt_tokens) + int(r.completion_tokens),
        )
        for r in rows
    ]


@router.get("/api/costs/deep", response_model=CostDeepOut)
def cost_deep_report(
    template_id: str | None = Query(None),
    task_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """深度成本报表：按 生成/质检 阶段拆分 + 多维（题型/模型/任务）聚合 + 单条下钻。

    口径：
    - 阶段拆分：按 TraceLog.stage（generate/qc）聚合成本与 token，量化生成与质检各自开销；
    - 多维聚合：按 题型/模型/任务 归并成本与 token（unknown 兜底）；
    - 单条下钻：列出最近 N 条 LLM 调用明细（token/成本/耗时），可下钻到单条。
    """
    base = db.query(TraceLog)
    if template_id:
        base = base.filter(TraceLog.template_id == template_id)
    if task_id:
        base = base.filter(TraceLog.task_id == task_id)

    # 全量合计
    agg = base.with_entities(
        func.count(TraceLog.id),
        func.coalesce(func.sum(TraceLog.cost), 0.0),
        func.coalesce(func.sum(TraceLog.prompt_tokens), 0),
        func.coalesce(func.sum(TraceLog.completion_tokens), 0),
    ).first()
    total_count, total_cost, total_prompt, total_completion = (
        int(agg[0]),
        float(agg[1]),
        int(agg[2]),
        int(agg[3]),
    )

    # 阶段拆分（按 stage 分组）
    stage_rows = (
        base.with_entities(
            TraceLog.stage,
            func.count(TraceLog.id),
            func.coalesce(func.sum(TraceLog.cost), 0.0),
            func.coalesce(func.sum(TraceLog.prompt_tokens), 0),
            func.coalesce(func.sum(TraceLog.completion_tokens), 0),
        )
        .group_by(TraceLog.stage)
        .all()
    )
    stages = [
        CostStageOut(
            stage=r[0] or "unknown",
            count=int(r[1]),
            total_cost=float(r[2]),
            prompt_tokens=int(r[3]),
            completion_tokens=int(r[4]),
            total_tokens=int(r[3]) + int(r[4]),
            prompt_cost=round(int(r[3]) / 1000.0 * settings.COST_PER_1K_TOKENS, 6),
            completion_cost=round(int(r[4]) / 1000.0 * settings.COST_PER_1K_TOKENS, 6),
        )
        for r in stage_rows
    ]

    by_template = _cost_by_key(db, TraceLog.template_id, "unknown")
    by_model = _cost_by_key(db, TraceLog.model, "unknown")
    by_task = _cost_by_key(db, TraceLog.task_id, "unknown")

    # 单条下钻（最近 N 条）
    trace_rows = base.order_by(TraceLog.created_at.desc()).limit(limit).all()
    traces = [
        CostTraceOut(
            trace_id=t.trace_id,
            model=t.model,
            stage=t.stage or "",
            template_id=t.template_id,
            task_id=t.task_id,
            prompt_tokens=t.prompt_tokens,
            completion_tokens=t.completion_tokens,
            total_tokens=(t.prompt_tokens or 0) + (t.completion_tokens or 0),
            cost=t.cost,
            latency_ms=t.latency_ms,
            created_at=t.created_at,
        )
        for t in trace_rows
    ]

    return CostDeepOut(
        total_cost=total_cost,
        total_count=total_count,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_tokens=total_prompt + total_completion,
        stages=stages,
        by_template=by_template,
        by_model=by_model,
        by_task=by_task,
        traces=traces,
    )


# ---------------------------------------------------------------------------
# 指标看板（PRD 第 15.1 节口径）
# ---------------------------------------------------------------------------
@router.get("/api/dashboard", response_model=DashboardOut)
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """指标看板聚合：生产量 / 质检通过率 / 人工驳回率 / 生产周期 / 成本。

    口径（对齐 PRD 15.1）：
    - 内容产出量：content_item 总数
    - 质检通过率：自动质检（source=auto）score >= QUALITY_THRESHOLD 占比
    - 人工驳回率：人工质检（source=manual_review）score=0 占比
    - 生产周期：generation_task created_at→updated_at 平均/最近时长
    - 单条成本：内容条目平均生成成本
    - 发布量：status=published 计数
    """
    # 内容总量与状态分布
    total_items = db.query(func.count(ContentItem.id)).scalar() or 0
    published = (
        db.query(func.count(ContentItem.id)).filter(ContentItem.status == "published").scalar() or 0
    )
    avg_cost_row = db.query(func.avg(ContentItem.cost)).scalar()
    avg_cost = float(avg_cost_row) if avg_cost_row is not None else 0.0
    total_cost = db.query(func.coalesce(func.sum(ContentItem.cost), 0.0)).scalar()

    # 自动质检通过率（source=auto，score>=threshold）
    auto_total = (
        db.query(func.count(QualityRecord.id)).filter(QualityRecord.source == "auto").scalar() or 0
    )
    auto_passed = (
        db.query(func.count(QualityRecord.id))
        .filter(QualityRecord.source == "auto")
        .filter(QualityRecord.score >= settings.QUALITY_THRESHOLD)
        .scalar()
        or 0
    )
    qc_pass_rate = auto_passed / auto_total if auto_total else 0.0

    # 人工驳回率（source=manual_review，score=0 即驳回）
    manual_total = (
        db.query(func.count(QualityRecord.id))
        .filter(QualityRecord.source == "manual_review")
        .scalar()
        or 0
    )
    manual_rejected = (
        db.query(func.count(QualityRecord.id))
        .filter(QualityRecord.source == "manual_review")
        .filter(QualityRecord.score == 0)
        .scalar()
        or 0
    )
    manual_reject_rate = manual_rejected / manual_total if manual_total else 0.0

    # 生产周期：任务平均时长（秒）
    avg_latency_row = db.query(
        func.avg(func.extract("epoch", GenerationTask.updated_at - GenerationTask.created_at))
    ).scalar()
    avg_latency = float(avg_latency_row) if avg_latency_row is not None else 0.0

    # 按题型质检通过率明细
    by_template = _dashboard_by_template(db)

    # 近 N 条已完成任务的生产周期明细
    task_latency = _dashboard_task_latency(db, limit=10)

    # 结构化输出符合率指标（P0-2：generate 阶段逐调用行 -> thread 级统计）
    gen_rows = (
        db.query(TraceLog.trace_id, TraceLog.attempt, TraceLog.success)
        .filter(TraceLog.stage == "generate")
        .all()
    )
    structured_stats = compute_structured_stats(
        [
            {
                "trace_id": r.trace_id,
                "attempt": r.attempt or 1,
                "success": bool(r.success),
            }
            for r in gen_rows
        ]
    )

    # 改版触发率：入库条目中经历过自动改版的占比
    revised_items = (
        db.query(func.count(ContentItem.id)).filter(ContentItem.revise_count >= 1).scalar() or 0
    )
    revise_trigger_rate = revised_items / total_items if total_items else 0.0

    kpis = [
        DashboardKpi(
            key="generated",
            label="内容产出量",
            value=float(total_items),
            unit="条",
            target=None,
            goal="higher_better",
        ),
        DashboardKpi(
            key="published",
            label="已发布量",
            value=float(published),
            unit="条",
            target=None,
            goal="higher_better",
        ),
        DashboardKpi(
            key="qc_pass_rate",
            label="质检通过率",
            value=round(qc_pass_rate * 100, 2),
            unit="%",
            target=90.0,
            goal="higher_better",
        ),
        DashboardKpi(
            key="manual_reject_rate",
            label="人工驳回率",
            value=round(manual_reject_rate * 100, 2),
            unit="%",
            target=5.0,
            goal="lower_better",
        ),
        DashboardKpi(
            key="avg_latency",
            label="平均生产周期",
            value=round(avg_latency, 1),
            unit="s",
            target=3600.0,
            goal="lower_better",
        ),
        DashboardKpi(
            key="avg_cost",
            label="单条平均成本",
            value=round(avg_cost, 6),
            unit="¥",
            target=None,
            goal="lower_better",
        ),
        DashboardKpi(
            key="structured_first_pass_rate",
            label="结构化首过率",
            value=round((structured_stats["first_pass_rate"] or 0.0) * 100, 2),
            unit="%",
            target=None,
            goal="higher_better",
        ),
        DashboardKpi(
            key="structured_avg_attempts",
            label="平均尝试次数",
            value=(
                round(structured_stats["avg_attempts"], 2)
                if structured_stats["avg_attempts"] is not None
                else 0.0
            ),
            unit="次",
            target=1.0,
            goal="lower_better",
        ),
        DashboardKpi(
            key="structured_failure_rate",
            label="结构化失败率",
            value=round((structured_stats["failure_rate"] or 0.0) * 100, 2),
            unit="%",
            target=0.0,
            goal="lower_better",
        ),
        DashboardKpi(
            key="revise_trigger_rate",
            label="改版触发率",
            value=round(revise_trigger_rate * 100, 2),
            unit="%",
            target=None,
            goal="lower_better",
        ),
    ]

    return DashboardOut(
        kpis=kpis,
        by_template=by_template,
        task_latency=task_latency,
        total_cost=float(total_cost or 0.0),
        generated_count=total_items,
        published_count=published,
    )


def _dashboard_by_template(db: Session) -> List[dict]:
    """按题型聚合：产出量 / 自动质检通过率。

    通过率与全局 KPI 同口径：基于 QualityRecord（source=auto 且 score>=threshold），
    而非 ContentItem.status（自动质检后状态仍为 pending_qc，仅人工复核/发布才变化）。
    """
    threshold = settings.QUALITY_THRESHOLD
    rows = (
        db.query(
            ContentItem.template_id,
            func.count(ContentItem.id).label("total"),
            func.sum(
                case(
                    (
                        (QualityRecord.source == "auto") & (QualityRecord.score >= threshold),
                        1,
                    ),
                    else_=0,
                )
            ).label("passed"),
        )
        .outerjoin(QualityRecord, QualityRecord.item_id == ContentItem.id)
        .group_by(ContentItem.template_id)
        .all()
    )
    result = []
    for r in rows:
        total = int(r.total)
        pass_cnt = int(r.passed or 0)
        result.append(
            {
                "template_id": r.template_id,
                "generated": total,
                "pass_rate": round(pass_cnt / total * 100, 2) if total else 0.0,
            }
        )
    return result


def _dashboard_task_latency(db: Session, limit: int = 10) -> List[dict]:
    """近 N 条任务的生产周期明细（秒）。"""
    rows = (
        db.query(
            GenerationTask.id,
            GenerationTask.template_id,
            GenerationTask.status,
            GenerationTask.created_at,
            GenerationTask.updated_at,
        )
        .order_by(GenerationTask.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "task_id": r.id,
            "template_id": r.template_id,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "latency_s": (
                round((r.updated_at - r.created_at).total_seconds(), 1)
                if r.updated_at and r.created_at
                else None
            ),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Trace 链路回放
# ---------------------------------------------------------------------------
@router.get("/api/traces", response_model=TraceListOut)
def list_traces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """列出最近的 trace 链路摘要（按 trace_id 去重聚合，最近优先）。

    每条含调用次数、累计成本、累计耗时与时间范围，便于在列表中选择链路回放。
    """
    total = db.query(func.count(func.distinct(TraceLog.trace_id))).scalar() or 0
    rows = (
        db.query(
            TraceLog.trace_id,
            func.max(TraceLog.task_id).label("task_id"),
            func.max(TraceLog.template_id).label("template_id"),
            func.count(TraceLog.id).label("call_count"),
            func.coalesce(func.sum(TraceLog.cost), 0.0).label("total_cost"),
            func.coalesce(func.sum(TraceLog.latency_ms), 0.0).label("total_latency_ms"),
            func.min(TraceLog.created_at).label("first_at"),
            func.max(TraceLog.created_at).label("last_at"),
        )
        .group_by(TraceLog.trace_id)
        .order_by(func.max(TraceLog.created_at).desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return TraceListOut(
        total=total,
        items=[
            TraceSummaryOut(
                trace_id=r.trace_id,
                task_id=r.task_id,
                template_id=r.template_id,
                call_count=int(r.call_count),
                total_cost=float(r.total_cost),
                total_latency_ms=float(r.total_latency_ms),
                first_at=r.first_at,
                last_at=r.last_at,
            )
            for r in rows
        ],
    )


@router.get("/api/traces/structured-stats", response_model=StructuredStatsOut)
def structured_stats(
    template_id: str | None = Query(None, description="按题型过滤"),
    task_id: str | None = Query(None, description="按任务过滤"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """结构化输出符合率统计（P0-2）。

    generate 阶段每次调用一行（含校验失败尝试，attempt/success 落库），
    按 thread（trace_id）聚合出首过率 / 平均尝试次数 / 最终失败率。
    """
    q = db.query(TraceLog.trace_id, TraceLog.attempt, TraceLog.success).filter(
        TraceLog.stage == "generate"
    )
    if template_id:
        q = q.filter(TraceLog.template_id == template_id)
    if task_id:
        q = q.filter(TraceLog.task_id == task_id)
    rows = q.all()
    stats = compute_structured_stats(
        [
            {
                "trace_id": r.trace_id,
                "attempt": r.attempt or 1,
                "success": bool(r.success),
            }
            for r in rows
        ]
    )
    return StructuredStatsOut(**stats)


@router.get("/api/traces/{trace_id}", response_model=list[TraceOut])
def get_trace(
    trace_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """按 trace_id 查询完整链路（所有 LLM 调用，按时间升序回放）。

    每条记录推断 stage：output_data 含 dimension_scores 视为质检（qc），否则为生成。
    """
    rows = (
        db.query(TraceLog)
        .filter(TraceLog.trace_id == trace_id)
        .order_by(TraceLog.created_at.asc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"trace not found: {trace_id}")
    result: list[TraceOut] = []
    for r in rows:
        out = TraceOut.model_validate(r)
        out.stage = "qc" if (r.output_data and "dimension_scores" in r.output_data) else "generate"
        result.append(out)
    return result


# ---------------------------------------------------------------------------
# 题型模板
# ---------------------------------------------------------------------------
@router.get("/api/templates", response_model=list[TemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("content:read")),
):
    """题型模板列表。"""
    return db.query(QuestionTemplate).order_by(QuestionTemplate.type_id).all()


# ---------------------------------------------------------------------------
# 模型档案
# ---------------------------------------------------------------------------
@router.post("/api/model-profiles", response_model=ModelProfileOut)
def create_model_profile(
    req: ModelProfileIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("template:manage")),
):
    """创建模型档案；若设为默认，则清除其他默认标记。"""
    if req.is_default:
        db.query(ModelProfile).update({ModelProfile.is_default: False})
    profile = ModelProfile(**req.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/api/model-profiles", response_model=list[ModelProfileOut])
def list_model_profiles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("content:read")),
):
    """模型档案列表。"""
    return db.query(ModelProfile).order_by(ModelProfile.name).all()


# ---------------------------------------------------------------------------
# 站内消息通知
# ---------------------------------------------------------------------------
@router.get("/api/notifications", response_model=NotificationListOut)
def list_notifications(
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """站内通知列表（分页），可只看未读，返回未读总数。"""
    query = db.query(AppNotification)
    if unread_only:
        query = query.filter(AppNotification.is_read.is_(False))
    unread = db.query(AppNotification).filter(AppNotification.is_read.is_(False)).count()
    total = query.count()
    rows = (
        query.order_by(AppNotification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return NotificationListOut(total=total, unread=unread, items=rows)


@router.get("/api/notifications/unread-count", response_model=UnreadCountOut)
def unread_notification_count(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """未读通知数（供前端角标）。"""
    count = db.query(AppNotification).filter(AppNotification.is_read.is_(False)).count()
    return UnreadCountOut(count=count)


@router.post("/api/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """标记单条通知已读。"""
    row = db.get(AppNotification, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    row.is_read = True
    db.commit()
    db.refresh(row)
    return row


@router.post("/api/notifications/read-all", response_model=UnreadCountOut)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """标记全部通知已读。"""
    db.query(AppNotification).update({AppNotification.is_read: True})
    db.commit()
    return UnreadCountOut(count=0)


# ---------------------------------------------------------------------------
# RAG 知识库
# ---------------------------------------------------------------------------
@router.post("/api/knowledge", response_model=KnowledgeUploadOut)
def upload_knowledge(
    req: KnowledgeUploadIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:write")),
):
    """上传一份资料（教材/课标/真题）并分块向量化入库。"""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="文本内容不能为空")
    chunks = index_document(
        db,
        source_type=req.source_type,
        source_name=req.source_name,
        text=req.text,
        knowledge_point=req.knowledge_point,
        meta=req.meta,
    )
    if chunks == 0:
        raise HTTPException(status_code=400, detail="分块失败，文本可能为空或过短")
    return KnowledgeUploadOut(
        chunks=chunks,
        source_type=req.source_type,
        source_name=req.source_name,
        knowledge_point=req.knowledge_point,
    )


# 上传文件大小上限（10 MB），防止异常大文件拖垮 embedding
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/api/knowledge/upload", response_model=KnowledgeUploadOut)
def upload_knowledge_file(
    file: UploadFile = File(...),
    source_type: str = Form("真题"),
    knowledge_point: str | None = Form(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:write")),
):
    """上传教研文档（txt/md/docx/pdf）并解析、分块向量化入库。

    文件名自动作为 source_name（去扩展名），便于按资料追溯。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    content = file.file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大（上限 10MB）")

    try:
        text = parse_file(file.filename, content)
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    source_name = Path(file.filename).stem
    chunks = index_document(
        db,
        source_type=source_type,
        source_name=source_name,
        text=text,
        knowledge_point=knowledge_point,
        meta={"filename": file.filename},
    )
    if chunks == 0:
        raise HTTPException(
            status_code=400, detail="解析后无可索引文本，文件可能为空或为纯图片 PDF"
        )
    return KnowledgeUploadOut(
        chunks=chunks,
        source_type=source_type,
        source_name=source_name,
        knowledge_point=knowledge_point,
    )


@router.get("/api/knowledge", response_model=KnowledgeListOut)
def list_knowledge(
    source_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """知识分块列表（分页，可按资料类型过滤）。"""
    stmt = select(KnowledgeChunk)
    if source_type:
        stmt = stmt.where(KnowledgeChunk.source_type == source_type)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = (
        db.execute(
            stmt.order_by(KnowledgeChunk.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return KnowledgeListOut(
        total=total,
        items=[KnowledgeChunkOut.model_validate(r) for r in rows],
    )


@router.delete("/api/knowledge/{chunk_id}")
def delete_knowledge(
    chunk_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:write")),
):
    """删除一条知识分块。"""
    row = db.get(KnowledgeChunk, chunk_id)
    if not row:
        raise HTTPException(status_code=404, detail="分块不存在")
    db.delete(row)
    db.commit()
    return {"deleted": chunk_id}


@router.get("/api/knowledge/retrieve", response_model=KnowledgeRetrieveOut)
def retrieve_knowledge(
    query: str,
    knowledge_point: str | None = None,
    top_k: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """向量检索最相关的知识分块，供调试与人工查看。"""
    snippets = retrieve(db, query=query, knowledge_point=knowledge_point, top_k=top_k)
    return KnowledgeRetrieveOut(query=query, snippets=snippets)


# ---------------------------------------------------------------------------
# 高质量回流样本（数据回流 / J2）
# ---------------------------------------------------------------------------
@router.post("/api/samples", response_model=SamplePoolOut)
def create_sample(
    req: SamplePoolIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:write")),
):
    """将一条高质量内容沉淀为回流样本（few-shot/微调语料）。"""
    item = db.get(ContentItem, req.content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="内容不存在")
    if item.status not in ("passed", "published"):
        raise HTTPException(status_code=400, detail="仅人工通过或已发布的内容可沉淀为样本")
    sample = pool_item(db, item, source=req.source, purpose=req.purpose)
    return sample


@router.post("/api/samples/sync", response_model=SampleSyncOut)
def sync_samples(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:write")),
):
    """自动将全部高质量内容（人工通过/已发布）沉淀为样本，幂等。"""
    added = sync_eligible(db)
    total = db.query(func.count(SamplePool.id)).scalar() or 0
    return SampleSyncOut(added=added, total=total)


@router.get("/api/samples", response_model=SamplePoolListOut)
def list_samples_api(
    template_id: str | None = Query(None),
    knowledge_point: str | None = Query(None),
    purpose: str | None = Query(None),
    source: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """回流样本检索（可按 题型/知识点/用途/来源 过滤，分页）。"""
    rows, total = list_samples(
        db,
        template_id=template_id,
        knowledge_point=knowledge_point,
        purpose=purpose,
        source=source,
        page=page,
        page_size=page_size,
    )
    return SamplePoolListOut(total=total, items=rows)


@router.get("/api/samples/export")
def export_samples(
    template_id: str | None = Query(None),
    knowledge_point: str | None = Query(None),
    purpose: str | None = Query(None),
    source: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:read")),
):
    """导出回流样本为 JSONL（few-shot/微调语料，每行一条样本）。"""
    rows, _ = list_samples(
        db,
        template_id=template_id,
        knowledge_point=knowledge_point,
        purpose=purpose,
        source=source,
        page=1,
        page_size=100000,
    )
    lines = []
    for s in rows:
        record = {
            "template_id": s.template_id,
            "source": s.source,
            "purpose": s.purpose,
            "knowledge_point": s.knowledge_point,
            "payload": s.payload,
            "meta": s.meta,
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    filename = "samples.jsonl"
    return PlainTextResponse(
        content="\n".join(lines),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/api/samples/{sample_id}")
def delete_sample(
    sample_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("ops:write")),
):
    """从回流样本库中移除一条样本。"""
    if not remove_sample(db, sample_id):
        raise HTTPException(status_code=404, detail="样本不存在")
    return {"deleted": sample_id}


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
@router.get("/api/health", response_model=HealthOut)
def health_check():
    """健康检查。"""
    return HealthOut(status="ok")

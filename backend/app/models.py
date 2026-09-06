# app/models.py —— SQLAlchemy 2.0 声明式模型
# 实现平台的 6 张核心表，字段对照架构文档第 7 节。
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_uuid() -> str:
    """生成字符串形式的 UUID 主键。"""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


# ---------------------------------------------------------------------------
# 1. 题型模板表
# ---------------------------------------------------------------------------
class QuestionTemplate(Base):
    """题型模板：定义生成某类题型所需的输入/输出结构、质量规则与提示词。"""

    __tablename__ = "question_template"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 题型唯一标识，如 single_choice
    type_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    quality_rules: Mapped[list] = mapped_column(JSONB, nullable=False)
    gen_prompt: Mapped[dict] = mapped_column(JSONB, nullable=False)
    run_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="enabled")
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# 2. 生成任务表
# ---------------------------------------------------------------------------
class GenerationTask(Base):
    """一次批量生成请求，记录切片子任务与整体进度。"""

    __tablename__ = "generation_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("question_template.type_id"), nullable=False, index=True
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 去重指纹：template_id + 规范化 params 的哈希，用于拦截重复提交
    request_hash: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 状态流转：pending -> running -> partially_succeeded/succeeded/failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trace_ref: Mapped[str] = mapped_column(String(128), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# 3. 内容条目表
# ---------------------------------------------------------------------------
class ContentItem(Base):
    """生成出的单条内容（含题干/选项/答案等载荷），待质检。"""

    __tablename__ = "content_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("generation_task.id"), index=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    qc_score: Mapped[float] = mapped_column(Float, nullable=True)
    # 状态流转：pending_qc -> passed / rejected / published；
    # awaiting_review（P1-1 灰区人工卡点，interrupt 暂停等待人工裁决）
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_qc")
    revise_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=True)
    # LangGraph 图线程 ID（thread_id=task:idx）；awaiting_review 条目凭此恢复裁决
    thread_id: Mapped[str] = mapped_column(String(128), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# 4. 质检记录表
# ---------------------------------------------------------------------------
class QualityRecord(Base):
    """自动/人工质检结果，含总分与各维度分。"""

    __tablename__ = "quality_record"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    item_id: Mapped[str] = mapped_column(ForeignKey("content_item.id"), index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 来源：auto（自动） / manual_review（人工）
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    reviewer: Mapped[str] = mapped_column(String(64), nullable=True)
    # 人工驳回原因（仅 manual_review 且驳回时填写，供反向校准分析）
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 5. 模型档案表
# ---------------------------------------------------------------------------
class ModelProfile(Base):
    """模型配置档案，用于路由主/备/默认模型。"""

    __tablename__ = "model_profile"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cost_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 6. 调用链路日志表
# ---------------------------------------------------------------------------
class TraceLog(Base):
    """记录每次 LLM 调用的链路信息，用于成本与可观测性分析。"""

    __tablename__ = "trace_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    item_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)
    # 所属题型（成本按题型聚合，避免依赖 item_id 关联）
    template_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    # 所属生成任务（用于成本按任务聚合，与 item_id 解耦）
    task_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=True)
    input_data: Mapped[dict] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=True)
    cost: Mapped[float] = mapped_column(Float, nullable=True)
    # 调用阶段：generate（生成）/ qc（质检），供深度成本按阶段拆分
    stage: Mapped[str] = mapped_column(String(32), nullable=True, index=True)
    # token 细分（供深度成本报表按生成/质检拆分 token 与成本）
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    # 本次调用为第几次尝试（1 起）；失败尝试同样落行（success=False），供首过率统计
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # 本次调用是否通过 Pydantic 二次校验
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 7. 站内消息表（通知）
# ---------------------------------------------------------------------------
class AppNotification(Base):
    """站内消息通知：任务完成/失败/内容被驳回等事件的通知。"""

    __tablename__ = "app_notification"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 通知类型：task_succeeded / task_partial / task_failed / content_rejected
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 关联对象（生成任务或缺值内容条目）
    related_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 9. 高质量回流样本表（数据回流 / J2）
# ---------------------------------------------------------------------------
class SamplePool(Base):
    """高质量回流样本：人工通过/发布的高质量内容沉淀为 few-shot / 微调语料。

    沉淀来源 source：manual（人工挑选）/ auto（自动同步人工通过项）。
    语料用途 purpose：fewshot / sft，供后续检索与导出消费。
    payload 为内容载荷快照，导出为 JSONL 语料时无需回查 content_item。
    """

    __tablename__ = "sample_pool"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 关联内容条目（人工通过/已发布，判定为高质量）
    item_id: Mapped[str] = mapped_column(
        ForeignKey("content_item.id"), unique=True, nullable=False, index=True
    )
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 沉淀来源：manual / auto
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    # 语料用途：fewshot / sft
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="sft")
    # 知识点标签（取自生成任务参数，供检索）
    knowledge_point: Mapped[str] = mapped_column(String(128), nullable=True, index=True)
    # 内容载荷快照（独立快照，导出无需回查内容表）
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 10. 质检校准记录表（J1 质量闭环）
# ---------------------------------------------------------------------------
class QualityCalibration(Base):
    """质检权重校准记录：用人工驳回样本反向校准 judge 维度权重。

    每次校准生成一条记录（append-only），get_effective_weights 取最新一条
    作为当前生效的覆盖权重。模板 quality_rules 保持默认值不被修改。
    """

    __tablename__ = "quality_calibration"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 校准后的生效权重（覆盖模板默认权重）
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    # 模板默认权重快照（供对比展示）
    default_weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    default_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    # 校准元信息
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    false_pass_cnt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 每维放水度（lenient_i = mean(FP 维度分) - mean(通过集 维度分)）
    lenient: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rejection_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 8. 知识库分块表（RAG）
# ---------------------------------------------------------------------------
class KnowledgeChunk(Base):
    """知识库分块：教材/课标/真题等资料按知识点分块并向量化，供生成时检索注入。"""

    __tablename__ = "knowledge_chunk"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 资料类型：教材 / 课标 / 真题
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 知识点标签，用于按知识点精确过滤
    knowledge_point: Mapped[str] = mapped_column(String(128), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 向量（维度与 embedding 模型输出一致，默认 1024）
    embedding: Mapped[list] = mapped_column(Vector(1024), nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 10. 平台用户表（K4 权限 / 多角色）
# ---------------------------------------------------------------------------
class User(Base):
    """平台用户：登录认证 + 角色权限。

    role 取值：admin（管理员）/ researcher（教研员）/ reviewer（质检员）/ viewer（查看者）。
    单租户多角色模式下 tenant_id 暂留空，为后续对外化多租户预留。
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # bcrypt 哈希后的密码，绝不落明文
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    # 状态：active（正常）/ disabled（禁用，禁用后不可登录与访问）
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

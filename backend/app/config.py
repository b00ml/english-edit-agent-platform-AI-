# app/config.py —— 全局配置（Pydantic Settings）
# 从环境变量（或 .env）读取平台运行配置，带类型化默认值，未设置时用默认值。
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_placeholder(value: str) -> bool:
    """识别示例文件中的空值和显式占位值。"""
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized.startswith("replace-with-")
        or normalized
        in {
            "sk-xxxxxxxx",
            "your-key",
            "your-secret",
        }
    )


class Settings(BaseSettings):
    """应用配置集合。

    所有字段均可由同名环境变量覆盖；int/float 字段自动做类型转换。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库连接串（SQLAlchemy 格式）
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/english_edit"

    # LangGraph checkpointer 后端：postgres（持久化断点，跨重启续跑）/ memory（进程内）。
    # postgres 初始化失败时自动降级 memory 并告警，保证可用性优先。
    CHECKPOINTER_BACKEND: str = "postgres"
    # 仅允许在 staging/production 显式放行 MemorySaver 降级；默认保持 not-ready。
    ALLOW_MEMORY_CHECKPOINTER: bool = False
    # Redis 连接串（数据队列 / Cache）
    REDIS_URL: str = "redis://localhost:6379/0"

    # Langfuse 可观测性配置（用于追踪 LLM 调用，可为空则关闭）
    LANGFUSE_HOST: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""

    # Trace 分发目标（逗号分隔）：db=自研 TraceLog 表（SSOT）；langfuse=可选导出通道。
    # 任一 sink 写入失败均不影响其余 sink 与业务主流程。
    TRACE_SINKS: str = "db"

    # OpenAI 兼容的云 API 配置
    LLM_API_BASE: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    # 默认模型名（无模型档案或档案缺失时兜底使用）
    LLM_MODEL_NAME: str = "deepseek-v4-flash"
    # judge 质检模型名（自偏好偏差治理：建议配置为与生成主模型不同家族的模型）。
    # 解析优先级：模板 run_config.judge_model > JUDGE_MODEL_NAME > LLM_MODEL_NAME。
    JUDGE_MODEL_NAME: str = ""
    # 生成/judge 采样温度（此前硬编码于引擎，配置化对齐"全配置驱动"口径）
    LLM_TEMPERATURE: float = 0.7
    JUDGE_TEMPERATURE: float = 0.3
    # 分模型价目表（每 1K token 单价）：{"模型名": {"prompt": x, "completion": y}}。
    # 未命中的模型回退 COST_PER_1K_TOKENS 单一单价（历史数据口径不变）。
    MODEL_PRICES: dict = {}
    # 单次 LLM 请求超时（秒）。显式设置而非依赖 SDK 默认 600s，避免连接挂起时单请求
    # 阻塞过久；超时抛 APITimeoutError，经 router 降级兜底处理。
    LLM_TIMEOUT: int = 120
    # 单次 embedding 请求超时（秒）
    EMBEDDING_TIMEOUT: int = 30

    # 结构化输出重试时是否回注校验错误信息（关闭则保持原样重发，兼容旧行为）
    STRUCTURED_RETRY_FEEDBACK: bool = True

    # Celery 任务可靠性（P0-6）
    # 任务级最大重试次数（仅瞬态基础设施错误：redis 连接/超时、DB OperationalError）
    TASK_MAX_RETRIES: int = 3
    # running 状态超过该秒数判定为僵尸任务，worker 启动时重置为 pending 并重新入队
    STALE_TASK_SECONDS: int = 1800

    # Outbox relay（数据库事务提交后投递 Celery）
    OUTBOX_MAX_ATTEMPTS: int = 5
    OUTBOX_RELAY_BATCH_SIZE: int = 50
    OUTBOX_RETRY_BACKOFF_SECONDS: int = 5
    # relay 领取到事件后进程异常时，超过该时间可重新领取；避免 sending 永久滞留。
    OUTBOX_SENDING_TIMEOUT_SECONDS: int = 300

    # 模型运行时治理（P2-1）；预算为 0 表示不启用全局上限。
    MODEL_COOLDOWN_SECONDS: int = 60
    MODEL_FAILURE_THRESHOLD: int = 2
    MODEL_MAX_FALLBACKS: int = 1
    MODEL_BUDGET_PER_TASK: float = 0.0

    # 成本估算单价（每 1000 token），用于记录 TraceLog.cost
    COST_PER_1K_TOKENS: float = 0.002

    # 质检 LLM 采样次数（降低抖动；rubric 已使单次稳定，默认 1，需降噪时调高）
    JUDGE_SAMPLE_ROUNDS: int = 1

    # 人工质检默认阈值
    QUALITY_THRESHOLD: float = 70.0

    # RAG 向量检索：OpenAI 兼容 embedding 端点（阿里云百炼 text-embedding-v3）
    EMBEDDING_API_BASE: str = "https://your-embedding-provider.example/v1"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL_NAME: str = "text-embedding-v3"
    # 向量维度（与 text-embedding-v3 默认输出一致）
    EMBEDDING_DIM: int = 1024

    # JWT 认证（K4 权限）
    # 生产环境务必通过环境变量覆盖默认密钥
    JWT_SECRET: str = "change-me-english-edit-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    # token 有效期（秒），默认 12 小时
    JWT_EXPIRE_SECONDS: int = 43200

    # 种子默认管理员账号（首次启动、用户表为空时自动写入；生产环境务必覆盖默认密码）
    SEED_ADMIN_USERNAME: str = "admin"
    SEED_ADMIN_PASSWORD: str = "admin123"
    SEED_ADMIN_DISPLAY_NAME: str = "系统管理员"

    # 环境标识（P0-5 生产环境 fail-fast）
    ENVIRONMENT: str = "development"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # P0-5 生产环境强制密钥检查
        if self.ENVIRONMENT == "production":
            if self.JWT_SECRET == "change-me-english-edit-jwt-secret" or _is_placeholder(
                self.JWT_SECRET
            ):
                raise ValueError("生产环境必须设置非占位 JWT_SECRET")
            if len(self.JWT_SECRET.encode("utf-8")) < 32:
                raise ValueError("生产环境 JWT_SECRET 至少需要 32 字节")
            if self.SEED_ADMIN_PASSWORD == "admin123" or _is_placeholder(self.SEED_ADMIN_PASSWORD):
                raise ValueError("生产环境必须设置非占位 SEED_ADMIN_PASSWORD")
            if _is_placeholder(self.LLM_API_KEY):
                raise ValueError("生产环境必须设置非占位 LLM_API_KEY")
            if _is_placeholder(self.EMBEDDING_API_KEY):
                raise ValueError("生产环境必须设置非占位 EMBEDDING_API_KEY")


settings = Settings()

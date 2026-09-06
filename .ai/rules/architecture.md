# .ai/rules/architecture.md —— 架构设计

## 分层架构
```
React 工作台 ──REST──> FastAPI 薄接口 ──入队──> Celery Worker
                                                    │
                                          LangGraph 状态机（生成→校验→质检→改版loop→入库）
                                                    │
                               engine（结构化输出/模型路由/LLM-judge）＋ rag（向量检索）
                                                    │
                                   PostgreSQL16+pgvector · Redis · Langfuse（Docker Compose）
```
- **入口层（api/）**：薄接口，只做参数校验、任务下发、查询，不承载业务逻辑。
- **编排层（workflow/）**：LangGraph 状态机，负责流程控制与状态流转。
- **引擎层（engine/）**：结构化输出、模型路由降级、LLM-judge 质检。
- **知识层（rag/）**：embedding / indexer / retriever，供生成前注入上下文。
- **队列层（worker/）**：Celery 消费批量任务，数量切片、进度更新、断点续跑。

## 核心模式
- **配置驱动（Configuration-driven）**：题型模板 YAML（input/output_schema、quality_rules、gen_prompt、run_config）驱动生成与质检；新增题型=新增 YAML，不改代码。
- **Adapter 隔离外部依赖**：云模型/embedding 经统一客户端接入；`router.resolve_model_profile` 负责主→备→默认降级，便于替换与测试。
- **Repository 访问数据**：DB 访问收敛到 `database.py` 会话与 `models.py`；API/workflow 不直接散落 SQL。

## 数据模型约定
- 8 张表：`question_template / generation_task / content_item / quality_record / model_profile / trace_log / knowledge_chunk / app_notification`（见 `models.py`）。
- 通用预留字段：`tenant_id`（对外化）、`created_by`、`created_at`、`updated_at`；类型用 `String(36)` UUID 主键。
- 结构化/动态字段一律 JSONB（`payload / params / input_schema / output_schema / dimension_scores / meta`）。
- JSONB 字段名统一用 `meta`，禁止 `_meta`。
- 状态流转用字符串常量集中定义，避免散落魔法值（见 `worker/tasks.py` 状态常量）。

## API 规范
- REST，前缀 `/api`；返回统一 Pydantic 响应模型（`schemas.py`）。
- 校验：入口用 Pydantic 请求模型；业务失败返回 4xx（404 不存在 / 400 参数错误）。
- 写操作幂等：生成任务提交带 `task_id`；重复提交去重（P1 目标）。
- 成本查询按 `template_id + model` 聚合，口径 = 生成 + 质检 token 成本。

## 配置管理
- 运行时配置（环境变量）统一 `app/config.py`，采用 Pydantic Settings 风格，集中声明。
- 禁止在业务代码里硬编码模型名 / 数据库串 / API Key；一律从 `settings` 读取。
- 类型化默认值 + 环境变量覆盖；敏感信息（Key）走项目根 `.env`，不入库不入代码。
- **配置源为项目根 `.env`**：docker-compose 从项目根读取（从项目根运行 `docker compose -f deploy/docker-compose.yml`）；本地直跑时 `.env` 相对运行目录，从项目根运行 uvicorn 即可命中。`.env` 已被 `.gitignore` 排除，不提交。

## 可观测性
- 每次 LLM 调用记录：`trace_id`、prompt 版本、模型、输入输出、`latency_ms`、`cost`。
- Langfuse 接入 FastAPI 与 worker，凭 `trace_id` 回放单次生成。
- 质量与成本口径（阈值 70 / 采样轮数 / 成本聚合）从配置读取，便于调优。

## 断点续跑
- LangGraph 开启 checkpointer；生产环境应替换为 `PostgresSaver` 持久化断点（当前用 `MemorySaver`）。
- 任务中断后重跑只生成未完成条目，已完成条目不重复生成。

# 英语教研 AI 内容生成平台 2.0 技术架构设计

> 配套文档：《AI内容生成平台2.0-PRD.md》
> 版本：V1.0（确定性开发文档）
> 场景：个人开发，单用户全量权限，预留对外化能力
> 环境：全栈 Docker 化部署

---

## 0. 技术决策总览（已确认）

| # | 决策项 | 确定选型 | 影响 |
|---|---|---|---|
| 1 | 核心编排层 | **LangGraph** | 工作流以代码定义图，可单测、可扩展 |
| 2 | 结构化输出 | **约束解码（Outlines）** | 解码层强制符合 JSON Schema，符合率趋近 100% |
| 3 | 模型推理部署 | **云 API 优先** | 零运维、快速上线，后续可按需自部署 |
| 4 | 主数据库 | **PostgreSQL** | JSONB 存结构化字段，与对外化衔接好 |
| 5 | 任务队列 | **Celery + Redis** | 并发控制、重试、断点续跑 |
| 6 | 可观测性 | **Langfuse 自建** | 全链路 Trace + Eval + 成本核算 |
| 7 | 约束解码实现库 | **Outlines** | 与 OpenAI 兼容 API 配合 |
| 8 | 前端界面 | **React 工作台（P0 即做）** | 首期即提供可视化工作台 |
| 9 | 部署方式 | **Docker Compose** | 全栈容器化，一键起环境 |

> 本文档所有章节均为已确定的技术方案，可直接进入开发。

---

## 1. 设计目标与原则

### 1.1 目标

- 支撑「选题 → 生成 → 校验 → 质检 → 改版 → 入库 → 发布」全链路可编排。
- 题型以配置化 Schema 接入，新增题型不改代码。
- 全链路可观测、可回放、成本可核算。
- 个人可维护、可迭代，为对外化预留扩展点。

### 1.2 技术原则

| 原则 | 落实方式 |
|---|---|
| 配置驱动 | 题型、质检规则、模型路由均为配置，不硬编码 |
| 结构化输出优先 | Outlines 约束解码 + JSON Schema 二次校验 |
| 可观测性内建 | Langfuse 从第一天接入 |
| 全栈容器化 | 所有组件 Docker Compose 编排 |
| 预留演进 | 数据模型预留 tenant_id / 权限扩展字段 |

---

## 2. 技术栈（最终确定）

| 层 | 选型 | 版本/说明 |
|---|---|---|
| 编排层 | **LangGraph** | 状态机定义流水线 |
| 后端 | **Python 3.12 + FastAPI** | 异步 API |
| 结构化输出 | **Outlines** + Pydantic v2 | 约束解码 + Schema 校验 |
| 任务队列 | **Celery 5** + Redis | worker 并发/重试/断点续跑 |
| 模型推理 | **云 API**（Qwen/DeepSeek/GLM，OpenAI 兼容） | 路由 + 降级 |
| 数据库 | **PostgreSQL 16** | JSONB 字段 |
| 缓存/队列 | **Redis 7** | Celery broker + 缓存 |
| 可观测性 | **Langfuse（Docker 自建）** | Trace/Eval/成本 |
| ORM | **SQLAlchemy 2 + Alembic** | 建模与迁移 |
| 前端 | **React 18 + Vite + TypeScript** | 工作台 |
| 部署 | **Docker Compose** | 后端/前端/DB/Redis/Langfuse |

---

## 3. 系统架构

```
┌────────────────────────────────────────────────────────────┐
│            React 工作台（生成/任务/质检/内容库/Trace/成本）       │
└───────────────────────────┬────────────────────────────────┘
                            │ REST / WebSocket
┌───────────────────────────▼────────────────────────────────┐
│                  API 层（FastAPI，薄接口）                      │
│         任务下发 · 模板管理 · 内容查询 · 质检标注 · 成本查询       │
└───────────────────────────┬────────────────────────────────┘
                            │ 入队
┌───────────────────────────▼────────────────────────────────┐
│          Celery Worker（消费生成任务）                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │   LangGraph 状态机：生成→校验→质检→改版loop→入库          │   │
│  │   （Outlines 约束解码 · LLM-judge 质检 · 模型路由）        │   │
│  └──────────────────────────────────────────────────────┘   │
└──────┬──────────────────────────────┬──────────────────────┘
       │                              │
┌──────▼────────┐              ┌──────▼──────────────┐
│  云 API 模型    │              │   RAG 检索（P1+）     │
│  Qwen/DeepSeek│              │  教材/课标/真题 chunk  │
└────────────────┘              └─────────────────────┘
┌─────────────────── 基础设施层（Docker Compose）──────────────────┐
│  PostgreSQL · Redis · Langfuse · 对象存储(预留)                    │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. LangGraph 工作流（确定性设计）

### 4.1 图结构与状态

**Graph State**：

```python
class GenState(TypedDict):
    task_id: str
    input_params: dict          # 知识点/难度/数量
    draft: dict | None          # 单条生成结果
    qc_score: float | None
    revise_count: int
    trace_id: str
    status: str                 # pending/generating/validating/qc/revising/done/failed
```

**节点与条件边**：

```
START → generate
generate → validate        (始终)
validate → qc              (校验通过)
validate → revise_fail     (重试达3次仍失败 → status=failed)
qc → done                  (score ≥ 70 → status=done, 入库)
qc → revise                (score < 70 → revise_count+1)
revise → generate          (revise_count < 3 → 携带质检反馈重新生成)
revise → rejected          (revise_count ≥ 3 → status=rejected)
revise_fail → END
done → END
rejected → END
```

### 4.2 断点续跑

- LangGraph 开启 **checkpointer**（SQLite/Postgres saver），保存每步状态。
- 任务中断后可加载 checkpoint 从断点继续，不重复生成已完成条目。

### 4.3 并发控制

- Celery worker `--concurrency=5`，单任务按 `quantity` 批量切片为子任务。
- 限制 in-flight 请求数，避免打爆云 API 配额。

---

## 5. 结构化输出引擎（确定性设计）

### 5.1 流程

1. 由模板 `output_schema` 生成 Outlines 约束 + Pydantic 模型。
2. 调用云 API 时携带 Outlines 的 JSON 约束，强制符合 schema。
3. 返回后 Pydantic 二次校验。
4. 校验失败 → 重试（默认 3 次）。
5. 重试耗尽仍失败 → 该条标记失败，不进入质检。

### 5.2 实现要点

- Outlines 通过 `outlines.generate.json(pydantic_model)` 或数据结构生成约束。
- 质检维度（单项选择示例）：知识点匹配 0.3、难度匹配 0.2、选项干扰性 0.3、无歧义 0.2。

---

## 6. 题型模板（Schema 驱动，确定性结构）

```yaml
# 题型模板：单项选择
type_id: single_choice
name: 单项选择
version: 1
input_schema:                # 生成输入参数
  type: object
  properties:
    knowledge_point: {type: string}
    difficulty: {type: string, enum: [易, 中, 难]}
    quantity: {type: integer, minimum: 1, maximum: 50}
  required: [knowledge_point, difficulty, quantity]
output_schema:               # 驱动 Outlines 约束解码
  type: object
  required: [stem, options, answer, explanation]
  properties:
    stem: {type: string}
    options:
      type: array
      items: {type: string}
      minItems: 4
      maxItems: 4
    answer: {type: string, enum: [A, B, C, D]}
    explanation: {type: string}
quality_rules:               # LLM-judge 打分维度（权重和=1）
  - {id: kp_match, weight: 0.3}
  - {id: diff_match, weight: 0.2}
  - {id: distractor, weight: 0.3}
  - {id: unambiguous, weight: 0.2}
gen_prompt:
  system: "你是资深英语教研员，严格按 JSON 格式输出。"
  user: "知识点：{{knowledge_point}}；难度：{{difficulty}}；生成 {{quantity}} 道单选题。"
run_config:
  model_profile: standard
  max_retry: 3
  max_revise: 3
  quality_threshold: 70
```

> 新增题型 = 新增一个 YAML 模板记录，运行时加载，不改代码。

---

## 7. 数据模型（确定性表结构）

| 表 | 核心字段 | 说明 |
|---|---|---|
| `question_template` | id, type_id(unique), name, version, input_schema(jsonb), output_schema(jsonb), quality_rules(jsonb), gen_prompt(jsonb), run_config(jsonb), status, tenant_id | 题型模板，版本化 |
| `generation_task` | id, template_id, params(jsonb), quantity, status, progress, trace_ref, created_at, tenant_id | 生成任务 |
| `content_item` | id, task_id, template_id, payload(jsonb), qc_score, status, revise_count, cost, tenant_id | 内容条目 |
| `quality_record` | id, item_id, score, dimension_scores(jsonb), source('auto'/'human'), reviewer, tenant_id | 质检记录 |
| `model_profile` | id, name, provider, model_name, cost_tier, is_default, tenant_id | 模型路由配置 |
| `trace_log` | id, item_id, trace_id, prompt_version, model, input, output, latency_ms, cost, tenant_id | 链路日志 |

> 通用预留字段：`tenant_id`（对外化）、`created_by`、`created_at`、`updated_at`。

---

## 8. 模型路由与成本（确定性设计）

- `model_profile` 定义模型（如 standard=Qwen2.5-72B，lite=DeepSeek），按题型复杂度/难度路由。
- 降级链：主模型 → 备用模型 → 全局默认。
- 成本口径：按 token 统计（生成 + 质检两部分），Langfuse 记录，按题型/模型/任务聚合。

---

## 9. 可观测性（Langfuse 自建）

- Docker 部署 Langfuse，SDK 接入 FastAPI 与 Celery worker。
- 每次生成记录：prompt 版本、模型、输入输出、质检分、耗时、成本。
- 凭 `trace_id` 回放单次生成，定位质量/成本根因。

---

## 10. 前端工作台（P0 即做）

**React 18 + Vite + TypeScript**，页面模块：

| 页面 | 功能 |
|---|---|
| 生成页 | 选择题型、填输入参数、发起批量生成 |
| 任务页 | 任务列表、进度、重试、断点续跑 |
| 质检页 | 自动质检结果、人工抽检标注（通过/驳回） |
| 内容库 | 检索、筛选、预览、发布/下架 |
| Trace 页 | 单次生成链路回放、耗时/成本查看 |
| 成本页 | 按题型/模型/任务成本聚合报表 |

> 前端通过 REST 调 FastAPI，WebSocket 推送任务进度。

---

## 11. 部署方案（Docker Compose，确定性）

**服务编排**：

| 服务 | 镜像 | 端口 |
|---|---|---|
| backend | Python 3.12（FastAPI） | 8000 |
| worker | 同 backend 镜像，celery 命令 | - |
| frontend | Node/nginx（React 构建） | 3000/80 |
| postgres | postgres:16 | 5432 |
| redis | redis:7 | 6379 |
| langfuse | langfuse/langfuse | 3001 |

**docker-compose 要点**：

- `backend` 与 `worker` 共享同一镜像与代码，仅 CMD 不同。
- Alembic 迁移在 backend 启动时执行。
- 网络：`english-edit-net` 内部互联，postgres/redis 不对外暴露端口。
- **配置源为项目根 `.env`**：Key（LLM/embedding）仅存于此，已被 `.gitignore` 排除；compose 的 `${VAR}` 插值从项目根 `.env` 读取。
- 本地开发：从项目根运行 `docker compose -f deploy/docker-compose.yml up -d --build`。

---

## 12. 目录结构（最终确定）

```
english-edit/
├── backend/
│   ├── api/            # FastAPI 路由（生成/任务/质检/内容/成本）
│   ├── workflow/       # LangGraph 图定义与状态
│   ├── templates/      # 题型模板 YAML
│   ├── engine/         # Outlines 约束解码、LLM-judge、模型路由
│   ├── worker/         # Celery 任务定义
│   ├── models/         # SQLAlchemy 模型
│   ├── migrations/     # Alembic 迁移
│   └── Dockerfile
├── frontend/           # React 工作台
│   ├── src/
│   └── Dockerfile
├── deploy/
│   └── docker-compose.yml
└── docs/               # 方案、PRD、本架构文档
```

---

## 13. 分阶段落地（确定性）

| 阶段 | 范围 | 交付物 |
|---|---|---|
| **P0 基础闭环** | 单选模板 + 生成→校验→质检→入库 + 前端工作台 | Docker 环境、LangGraph 单选流水线、生成/任务/内容库页面 |
| **P1 骨架扩展** | 完形/阅读模板 + 断点续跑 + 模型路由降级 + RAG | 模板扩展至 3 类、任务队列稳定、质检/成本页面 |
| **P2 质量优化** | 质检校准 + 数据回流 + 微调(QLoRA) | judge 校准、高质量样本回流、可选微调 |
| **P3 平台完善** | Trace 深度回放 + 成本报表 + 对外化预留 | 完整监控与成本体系 |

---

## 14. 开发环境要求

- Docker + Docker Compose（后端、DB、Redis、Langfuse 全容器化）。
- 云 API Key（Qwen/DeepSeek/GLM 任一，OpenAI 兼容）。
- Node 18+（前端构建，可选容器内构建）。

---

## 15. 风险与控制

| 风险 | 控制措施 |
|---|---|
| 云 API 配额/费用 | 并发控制 + 量小题型走 lite 模型 + 成本报表监控 |
| 质检打分不稳定 | judge 多次采样取均值，人工抽检校准 |
| 题型扩展失控 | Schema 模板约束 + 版本管理 |
| 断点续跑准确性 | LangGraph checkpoint 持久化 + 单测 |
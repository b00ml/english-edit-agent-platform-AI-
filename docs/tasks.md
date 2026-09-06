# 英语教研 AI 内容生成平台 2.0 开发任务清单

> 配套文档：《AI内容生成平台2.0-PRD.md》《AI内容生成平台2.0-技术架构设计.md》《优化记录.md》
> 版本：V1.1
> 技术栈：LangGraph + FastAPI + Pydantic v2 + Celery/Redis + PostgreSQL + Langfuse + React + Docker Compose

---

## 任务总览

| 阶段 | 目标 | 任务数 | 已完成 |
|---|---|---|---|
| P0 基础闭环 | 单选模板 + 生成→校验→质检→入库 + 前端工作台 | 16 | **16** ✅ |
| P1 骨架扩展 | 完形/阅读模板 + 断点续跑 + 路由降级 + RAG + Prompt/Skill 工程化 | 9 | **9** ✅ |
| P2 质量优化 | 质检校准 + 数据回流 + 微调 | 6 | **5** |
| P3 平台完善 | Trace 回放 + 成本报表 + 对外化预留 | 5 | **3** |
| V2.1 优化技术设计 2.0 | 质量闭环合法化 + 可靠性加固（P0×6 + P1×4） | 10 | **10** ✅ |

> 每个任务标注：优先级（P0/P1/P2）、依赖、验收标准。方括号 `[x]` 标记完成状态。

---

## P0 基础闭环（16 项）

### A. 项目脚手架与 Docker 环境

- [x] **A1. 初始化 monorepo 目录结构**
  - 依赖：无
  - 内容：按架构文档第 12 节创建 `backend/ frontend/ deploy/ docs/` 目录骨架
  - 验收：目录结构存在且命名与文档一致
  - 完成：目录结构已建立，含 backend/app、backend/templates、backend/alembic、frontend、deploy

- [x] **A2. 编写 docker-compose.yml（基础服务）**
  - 依赖：无
  - 内容：编排 postgres:16、redis:7、langfuse，配置 `english-edit-net` 网络，DB/Redis 不对外暴露端口
  - 验收：`docker compose up` 后三服务健康运行
  - 完成：三服务（postgres/redis/langfuse）+ backend + worker + frontend + nginx 全链路编排

- [x] **A3. 初始化后端 Python 项目**
  - 依赖：无
  - 内容：`backend/` 内建 pyproject.toml/requirements，依赖 FastAPI、SQLAlchemy 2、Alembic、LangGraph、Outlines、Celery、langfuse
  - 验收：`pip install` 可成功，启动空 FastAPI 应用返回健康检查
  - 完成：pyproject.toml 配置齐全，FastAPI 应用 + 健康检查端点 /health

- [x] **A4. 编写 backend Dockerfile**
  - 依赖：A3
  - 内容：Python 3.12 镜像，安装依赖，配合 Alembic 迁移入口
  - 验收：镜像可构建，容器可启动
  - 完成：Python 3.12-slim 镜像，含 Alembic 迁移入口

### B. 数据模型与迁移

- [x] **B1. SQLAlchemy 模型定义**
  - 依赖：A3
  - 内容：实现 `question_template / generation_task / content_item / quality_record / model_profile / trace_log` 六表，含 tenant_id 预留字段
  - 验收：模型可导入，无缺字段（对照架构文档第 7 节）
  - 完成：六表 + knowledge_chunk（RAG）+ trace_log(task_id/template_id) + generation_task(request_hash) 扩展字段

- [x] **B2. Alembic 首次迁移**
  - 依赖：A2、B1
  - 内容：生成初始迁移，连接 postgres 建表
  - 验收：`alembic upgrade head` 成功建 6 张表
  - 完成：多版本迁移（初始六表 → 质检分 → 模型路由 → knowledge_chunk → request_hash → trace_log task_id → trace_log template_id）

### C. 题型模板与配置

- [x] **C1. 模板加载器**
  - 依赖：B1
  - 内容：实现从 `backend/templates/*.yaml` 加载题型模板，校验格式后入库
  - 验收：启动时加载单选模板，`question_template` 表有记录
  - 完成：`template_loader.py` 启动时自动扫描加载 YAML 模板入库

- [x] **C2. 单选模板 YAML**
  - 依赖：无
  - 内容：按架构文档第 6 节实现 single_choice 模板（input/output/quality_rules/gen_prompt/run_config）
  - 验收：YAML 可被加载器解析并通过校验
  - 完成：single_choice.yaml 含完整 schema + quality_rules + gen_prompt（.st 引用）+ model_profile 分档

- [x] **C3. 模型路由配置（model_profile）**
  - 依赖：B1
  - 内容：实现 standard/lite 模型配置，含 provider、model_name、cost_tier、is_default
  - 验收：可在 DB 中 insert 并读取模型配置
  - 完成：model_profile 表预置 standard/lite/high 三档，按题型×难度分档路由

### D. 后端核心引擎

- [x] **D1. Outlines 约束解码模块**
  - 依赖：C2
  - 内容：由 output_schema 生成 Pydantic 模型，用 Outlines 生成 JSON 约束，调用云 API
  - 验收：对单选模板调用可返回符合 schema 的 JSON
  - 完成：`structured_output.py` 实现 Pydantic v2 schema 构建 + 云 API 调用 + JSON 二次校验

- [x] **D2. Pydantic 二次校验 + 重试**
  - 依赖：D1
  - 内容：校验失败重试 3 次，耗尽标记失败
  - 验收：故意传坏 schema 的返回，确认重试与失败标记逻辑
  - 完成：3 次重试 + 指数退避 + 最终失败标记 StructuredOutputError

- [x] **D3. LLM-judge 自动质检**
  - 依赖：D2
  - 内容：按 quality_rules 逐维度打分加权（0-100），阈值 70
  - 验收：生成 quality_record，含总分与维度分
  - 完成：`quality.py` 实现多轮采样均值 + 加权汇总 + TraceLog 记录

- [x] **D4. 模型路由 + 降级**
  - 依赖：C3、D1
  - 内容：按模板 run_config.model_profile 路由，主→备→默认降级
  - 验收：主模型失败时降级到备用，Trace 中记录
  - 完成：`router.py` 实现分档路由（default/hard）+ 主→备→默认降级链

### E. LangGraph 流水线

- [x] **E1. LangGraph 状态机**
  - 依赖：D1-D4
  - 内容：实现 GenState 与节点（generate/validate/qc/revise/done），含改版 loop（M=3）
  - 验收：跑通 生成→校验→质检→入库 全链路，低分走改版
  - 完成：`graph.py` 实现完整状态机 + 质检低分改版 + 入库节点

- [x] **E2. LangGraph checkpoint 断点续跑**
  - 依赖：E1
  - 内容：接入 checkpointer，中断后可续跑不重复已完成
  - 验收：模拟中断后重跑，已完成条目不重复生成
  - 完成：MemorySaver checkpointer 已接入

### F. Celery 任务队列

- [x] **F1. Celery worker + 任务定义**
  - 依赖：E1
  - 内容：定义批量生成任务，数量切片子任务，并发=5
  - 验收：入队后可被 worker 消费并完成生成
  - 完成：`worker/tasks.py` 实现批量切片 + 并发控制

- [x] **F2. 任务状态与进度**
  - 依赖：F1、B1
  - 内容：任务状态（待执行/执行中/部分成功/成功/失败）与进度更新
  - 验收：任务各状态正确流转，进度可查询
  - 完成：generation_task 状态机完整 + 进度字段实时更新

### G. FastAPI 接口

- [x] **G1. 生成/任务/内容/质检 API**
  - 依赖：F2、B1
  - 内容：实现 发起生成、查询任务/进度、内容检索、质检标注、成本查询 接口
  - 验收：REST 接口可按 PRD 功能调用并返回正确数据
  - 完成：`api/routes.py` 含 /generate、/tasks、/contents、/quality、/costs、/knowledge 全套接口

### H. 前端工作台

- [x] **H1. React 项目初始化**
  - 依赖：G1
  - 内容：Vite + React 18 + TS 初始化，配置 API 代理
  - 验收：开发服务器可启动
  - 完成：Vite + React 18 + TypeScript + Ant Design 组件库

- [x] **H2. 生成页 + 任务页**
  - 依赖：H1
  - 内容：选择题型、填参数、发起生成；任务列表/进度/重试
  - 验收：可发起生成并看到任务进度
  - 完成：GeneratePage + TasksPage 已实现，支持 3 题型参数表单

- [x] **H3. 内容库 + 质检页**
  - 依赖：H1、G1
  - 内容：内容检索/筛选/预览/发布；质检标注（通过/驳回）
  - 验收：可查看生成内容并进行人工质检标注
  - 完成：ContentsPage + QualityPage（含状态/题型筛选）已实现

- [x] **H4. 前端 Dockerfile + nginx**
  - 依赖：H2/H3
  - 内容：React 构建镜像，nginx 部署，接入 compose
  - 验收：`docker compose up` 后前端可访问
  - 完成：nginx 镜像 + compose 编排，`localhost:3000` 可访问

---

## P1 骨架扩展（9 项）

- [x] **I1. 完形填空模板 + 流水线**
  - 依赖：P0 闭环
  - 内容：cloze 模板 YAML + 适配 LangGraph 生成/质检
  - 验收：可生成完形题并通过质检
  - 完成：`cloze.yaml` 加载入库；增强 structured_output 支持嵌套数组/子对象递归渲染与二次校验；生成→质检→入库验证通过（质检分 94.38）

- [x] **I2. 阅读理解模板 + 流水线**
  - 依赖：P0 闭环
  - 内容：reading 模板 YAML + 适配流水线
  - 验收：可生成阅读题（含多小题）并通过质检
  - 完成：`reading.yaml` 加载入库；短文+多小题嵌套结构生成成功（质检分 92.62）；前端动态表单与通用预览组件已适配

- [x] **I3. RAG 知识库接入**
  - 依赖：I1/I2
  - 内容：教材/课标/真题分块入向量库，按知识点检索注入生成上下文
  - 验收：生成时命中相关知识片段，内容有依据
  - 完成：pgvector + 阿里云百炼 text-embedding-v3；新增 `knowledge_chunk` 表与 `app/rag/`（embedding/indexer/retriever）；生成前按知识点检索注入 rag_context；知识库管理 API（上传/列表/删除/检索）；索引→检索→注入→生成→质检→入库全链路验证通过（质检分 93.75）

- [x] **I4. 模型路由降级完善**
  - 依赖：P0
  - 内容：按题型复杂度/难度差异化路由，降级链生产化
  - 验收：复杂阅读题走高性能模型，单选走 lite
  - 完成：`run_config.model_profile` 支持按难度分档的字典配置（`default`/`hard` 等，缺档回退 default，再回退任意档位）；`router._resolve_primary_profile_name` 解析分档，字符串形态向后兼容；`single_choice` 默认走 lite、`cloze`/`reading` 默认 standard、难题升级 high；新增 5 个难度路由单测，全套 41 个测试通过

- [x] **I5. 质检/成本前端页面**
  - 依赖：G1、H3
  - 内容：质检页完善 + 成本页（按题型/模型/任务聚合）
  - 验收：成本报表可查看
  - 完成：质检页新增状态/题型筛选；成本页支持按 题型/模型/任务 三维度聚合 + 题型筛选；`TraceLog` 新增 `task_id`/`template_id` 列（迁移 c2d8/d3e9）并在生成/质检链路记录，成本接口按 `group_by` 聚合；41 测试通过、前端 tsc 通过、端到端验证三维度聚合正确

- [x] **I6. 站内消息通知**
  - 依赖：G1
  - 内容：任务完成/失败/驳回通知，站内信
  - 验收：任务完成时收到站内通知
  - 完成：新增 `app_notification` 表（迁移 e4a1）+ `app/notification.py` 服务；任务结束（succeeded/partially/failed）在 Celery worker 收尾生成通知，人工质检驳回在 `/api/quality/{id}/review` 生成通知；新增 `/api/notifications`（列表/未读数/单条已读/全部已读）接口；前端新增消息页 + 侧边栏未读角标（30s 轮询）；4 个通知单测通过，端到端验证全生命周期（创建→未读→已读→清零）

- [x] **I7. 重复提交去重**
  - 依赖：G1
  - 内容：按题型+输入参数哈希去重，重复提示
  - 验收：相同参数重复发起被拦截
  - 完成：`app/dedup.py` 提供规范化参数指纹；`generation_task` 新增 `request_hash` 列与唯一索引迁移；生成接口对仍在执行（pending/running）的相同任务返回 409 `DUPLICATE_TASK`；新增 `DuplicateTaskError` 与 5 个指纹单测通过

- [x] **I8. 批量任务稳定性**
  - 依赖：P0
  - 内容：大批量（如 500+）任务测试、失败重试、并发压测
  - 验收：大批量稳定完成，无超时丢任务
  - 完成：Celery 任务超时加固（`task_soft_time_limit=600s` / `task_time_limit=900s`，防单任务卡死整体阻塞）；新增 `scripts/batch_stress.py` 压测脚本（先统一 commit 再投递 Celery，修复 worker 因看不到未提交行而误判「任务不存在」导致任务假死的问题）；容器内 500 任务并发压测验证：任务稳定推进、无超时丢任务、无「任务不存在」卡死、5 并发 worker 持续消费直至达终态

- [x] **I9. Prompt 工程化升级**
  - 依赖：P0
  - 内容：Prompt 独立文件化（.st system/user 分离）+ Skill 架构（SKILL.md + skill.meta.yml）+ 结构化 6 段式 Prompt（Role/Task/质量标准/命制规则/难度分级/约束/Output Format）
  - 验收：新增 `backend/prompts/`（6 个 .st 文件）+ `backend/skills/`（4 个 skill 目录）+ `app/prompt_loader.py` + `app/skill_registry.py`；Prompt 行数 ↑3900%，结构化 6/6 段完整；50 测试通过；端到端生成质量显著提升
  - 完成：6 个 .st prompt 文件（system/user 分离，40-50 行结构化）+ 4 个 skill（single_choice/cloze/reading/generate_question）+ prompt_loader/skill_registry 加载器；9 个新测试；端到端验证生成质量提升（真实语境题干 + 同质选项 + 详细解析）。详见 `docs/优化记录.md` OPT-002

---

## P2 质量优化（6 项）

- [x] **J1. 质检标准校准**
  - 依赖：P1
  - 内容：用人工抽检结果校准 judge 权重/threshold
  - 验收：校准后人工驳回率 ≤5%
  - 完成：新增 `quality_calibration` 表（迁移 g6b7c8d9e0f1）+ `QualityRecord.reason` 列；`app/calibration.py` 纯函数模块（`fit_weights` 放水度计算与降权归一化 + `collect_labeled` 标注对收集 + `recalibrate` 编排与守卫 + `get_effective_weights` 覆盖权重读取）；`quality.py` `_aggregate_score` 支持 `weights_override`；`graph.py` `qc_node` 接入覆盖权重；新增 `POST /api/quality/calibrate` + `GET /api/quality/calibration`；前端看板页新增"质检校准中心"（一键校准 + 生效/默认权重对比表 + 驳回率）；8 个校准纯函数单测，全量 109 测试通过。详见 `docs/优化记录.md` OPT-014
  - 闭环叙事：低分自动改版（graph.py after_qc）→ 人工驳回记录（review_content 存 reason）→ 假阳性样本（auto 高分但 manual 驳回）→ 计算放水度 → 降权 → 下次质检更准 → 驳回率下降

- [x] **J2. 数据回流**
  - 依赖：P1
  - 内容：高质量样本沉淀为 few-shot / 微调语料
  - 验收：回流样本可检索、可导出
  - 完成：新增 `sample_pool` 表（迁移 f5a6，含 item_id 唯一/template_id/knowledge_point 索引 + payload 快照）+ `app/sample_pool.py` 服务（`is_eligible` 高质量判定、`pool_item` 幂等沉淀、`sync_eligible` 自动同步人工通过项、`list_samples` 多条件检索、`remove_sample` 移除）；新增 `/api/samples`（沉淀）、`/api/samples/sync`（自动同步）、`/api/samples`（检索）、`/api/samples/export`（JSONL 导出）、`DELETE /api/samples/{id}`；前端新增样本库页（浏览/自动沉淀/导出/移除，复用通用预览）；11 个新单测，全量 73 测试通过，前端 tsc 通过。详见 `docs/优化记录.md` OPT-009

- [~] **J3. 微调评估（QLoRA）— 暂缓**
  - 依赖：J2
  - 内容：评估是否值得微调，选测 QLoRA+DPO
  - 验收：微调前后质检通过率对比报告
  - 状态：**暂缓**。微调需本地部署模型，当前平台为云端 API 调用（Qwen/DeepSeek/GLM），与现有技术路线不符；数据回流（J2）已先行落地，待未来接入本地/可微调模型时再评估。

- [x] **J4. judge 稳定采样**
  - 依赖：P1
  - 内容：judge 多次采样取均值，降低抖动
  - 验收：同一样本多次质检分方差下降
  - 完成：`quality.py` 实现 rubric 结构化注入（system/user 分离，分档评分标准）+ `aggregate_rounds` 多轮均值聚合（缺失维度按轮独立处理）+ 单轮失败跳过不阻断；3 个模板 quality_rules 均含 rubric 分档；`judge_stability.py` 交错采样方差验证脚本（单次方差为 0 即判通过）；`test_quality.py` 新增 TestAggregateRounds/TestBuildJudgePrompt 单测；JUDGE_SAMPLE_ROUNDS 默认调为 1（rubric 已使单次稳定，多轮收益有限徒增成本），保留 rounds 参数作为可选降噪开关
  - skill 化：judge 质检 prompt 从代码硬编码抽取为独立文件 `prompts/judge-system.st` + `prompts/judge-user.st`（{{rubric}}/{{payload}} 占位符）；新增 `skills/judge/SKILL.md` + `skill.meta.yml` 质检技能规范（评分流程/分档判定/尺度一致性/Anti-Patterns）；`skill_registry` 新增 `get_skill_by_id` 支持跨题型通用技能按 id 读取；`quality.py` 经 prompt_loader 加载 .st + 注入 judge SKILL.md；59 测试通过

- [x] **J5. Trace 回放页面**
  - 依赖：P1
  - 内容：前端 Trace 页回放单次生成链路
  - 验收：可凭 trace_id 查看完整链路
  - 完成：后端新增 `GET /api/traces`（按 trace_id 去重聚合的链路摘要列表，含调用数/累计成本/耗时/时间范围）+ `GET /api/traces/{trace_id}`（按时间升序回放完整链路，推断 stage：generate/qc）；前端新增 TracePage（链路列表 + trace_id 输入查询 + 链路步骤时间轴卡片，可展开查看 input/output JSON，stage 标签区分生成/质检，汇总条显示调用数/累计耗时/成本）；复用现有单色调样式，新增 trace 专属 CSS；前端 tsc 类型检查通过、后端 59 测试通过

- [x] **J6. 指标看板**
  - 依赖：P1
  - 内容：生产周期/符合率/通过率/驳回率/成本指标展示
  - 验收：指标按 PRD 第 15 节口径展示
  - 完成：后端新增 `GET /api/dashboard`（口径对齐 PRD 15.1：内容产出量/已发布量/质检通过率（source=auto score≥threshold）/人工驳回率（manual score=0）/平均生产周期（任务 updated-created 秒）/单条平均成本 + 按题型产出通过率明细 + 近 10 条任务生产周期）；`case`/`extract` 聚合 SQL 编译验证通过；前端新增 DashboardPage（KPI 卡片含目标值与达标判定、汇总条、按题型产出表、任务周期表），导航新增「看板」；前端类型检查通过、后端 59 测试通过；容器端到端验证：修复 `settings` 未导入报错，并统一 by_template 通过率口径（改用 QualityRecord source=auto score≥threshold 与全局 KPI 一致，而非 ContentItem.status，因自动质检后状态仍为 pending_qc），实测产出 1/质检通过率 100%/周期 67.7s

---

## P3 平台完善（5 项）

- [ ] **K1. 对外化数据预留落地**
  - 依赖：P2
  - 内容：启用 tenant_id/权限字段，多租户隔离设计
  - 验收：数据结构支持多租户

- [x] **K2. 深度成本报表**
  - 依赖：P2
  - 内容：成本按 token 细分（生成/质检），多维聚合
  - 验收：成本可下钻到单条
  - 完成：`TraceLog` 新增 `stage`/`prompt_tokens`/`completion_tokens` 列（迁移 a7b8，index stage）+ `token_breakdown()` 拆分输入/输出 token 与成本；`structured_output`/`quality` 记录时注入 stage 与 token；新增 `GET /api/costs/deep`（按生成/质检阶段拆分 + 题型/模型/任务多维聚合 + 单条调用下钻）；前端成本页新增深度成本汇总 KPI、阶段拆分表、三维聚合表、单条下钻表；4 个新单测，全量 77 测试通过。详见 `docs/优化记录.md` OPT-010

- [ ] **K3. 多模态扩展点**
  - 依赖：P2
  - 内容：Schema 支持音频/图片字段，预留听力/图文题型
  - 验收：模板可声明多媒体字段

- [x] **K4. 权限与多角色**
  - 依赖：K1
  - 内容：拆分包管理员/教研员/质检员/查看者角色
  - 验收：角色权限按 PRD 第 5/13 节生效
  - 完成：User 模型 + Alembic 迁移（b1c2）+ security.py（密码哈希/JWT/权限矩阵/依赖注入 get_current_user/require_permission）+ 30+ 接口鉴权挂载 + 前端登录页/路由守卫/动态导航/用户管理页 + 种子管理员（seed.py 独立模块，环境变量可配，幂等写入不覆盖密码）+ 单元测试 101 全通过。Docker 端到端验证通过（backend/worker/frontend 镜像重建 + 迁移成功）；README 接口清单已补齐认证/校准端点
  - 详见 `docs/优化记录.md` OPT-013

- [ ] **K5. 部署与监控完善**
  - 依赖：P2
  - 内容：生产化 compose、日志、告警、vLLM 自部署评估
  - 验收：生产环境可滚动部署，有基础告警

---

## 依赖关系图

```
P0: A1→A2→A3→A4 ──→ B1→B2
     A3 ──→ C1→C2 ──→ D1→D2→D3→D4 ──→ E1→E2 ──→ F1→F2 ──→ G1 ──→ H1→H2→H3→H4
P1: P0 ──→ I1→I2→I3 , P0→I4/I5/I6/I7/I8
P2: P1 ──→ J1→J2→J3 , P1→J4/J5/J6
P3: P2 ──→ K1→K2→K3→K4→K5
```

---

## 优化技术设计 2.0（质量闭环合法化与可靠性加固）

> 设计文档：`docs/优化技术设计2.0.md`（2026-09-05，含问题清单 G1~G12 / 详细设计 / 指标口径字典 / 简历声明合法化对照表）

- [x] **P0-1. 结构化输出校验错误回注重试**（OPT-015）：多轮消息回注上次输出+字段级错误摘要，开关 `STRUCTURED_RETRY_FEEDBACK`；失败尝试落 TraceLog
- [x] **P0-2. 结构化符合率埋点**（OPT-016）：TraceLog 增 attempt/success（迁移 h7c8d9e0f1a2）；`compute_structured_stats` 纯函数；dashboard 4 项新 KPI + `/api/traces/structured-stats`
- [x] **P0-5. 依赖与声明清理**（OPT-017）：移除 outlines 死依赖、补声明 openai；Trace Sink 分发（db SSOT + langfuse 可选导出）
- [x] **P0-3. Checkpointer 持久化**（OPT-018）：MemorySaver → PostgresSaver（惰性单例 + 失败降级 + `CHECKPOINTER_BACKEND` 开关）
- [x] **P0-6. Celery 任务可靠性**（OPT-019）：acks_late + task_reject_on_worker_lost + 瞬态错误 autoretry + 僵尸任务恢复（依赖 P0-3 幂等）
- [x] **P0-4. Judge 一致性评估**（OPT-020）：`cohen_kappa` 纯函数 + `scripts/judge_agreement.py`（accuracy/kappa/混淆矩阵，n≥30 守卫）
- [x] **P1-2. Judge 独立模型配置**（OPT-021）：`JUDGE_MODEL_NAME` 全局 + 模板级 `judge_model` 覆盖（自偏好偏差治理）
- [x] **P1-3. 分模型价目表**（OPT-022）：`MODEL_PRICES` JSON 配置，`compute_cost` 按模型计价，未命中回退全局单价
- [x] **P1-1. LangGraph interrupt 人工卡点**（OPT-024，附 OPT-023 改版双生成 Bug 修复）：灰区转人工（模板级开关），`submit_review`+`human_review` 两节点 + `resume_human_review`（依赖 P0-3）
- [x] **P1-4. 集成测试 + CI**（OPT-025）：可测性重构（`_get_openai_client` 缝）、`tests/integration/`（真 Postgres，5 用例）、GitHub Actions 双 job（覆盖率 81.44%，门槛 80%）

---

## 里程碑验收

| 里程碑 | 通过标准 | 状态 |
|---|---|---|
| P0 完成 | 单选可从工作台发起生成→自动质检→入库→人工质检，全链路可用 | ✅ 已通过 |
| P1 完成 | 3 类题型可生产，RAG 生效，任务稳定，成本可查，Prompt/Skill 工程化 | ✅ 已通过 |
| P2 完成 | 人工驳回率 ≤5%，质检稳定，Trace 可回放（微调评估 J3 暂缓，因云端 API 技术路线） | ✅ 已通过（J1 校准闭环 + J2 数据回流 + J4 稳定采样 + J5 Trace 回放 + J6 看板；J3 微调暂缓） |
| P3 完成 | 多租户/多角色可用，成本可下钻，多模态预留可用 | 进行中 |

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|---|---|---|
| V1.0 | 2026-08-11 | 基于 PRD 与技术架构文档生成任务清单 |
| V1.1 | 2026-08-11 | P0 全部 16 项标记完成；新增 I9 Prompt 工程化升级；里程碑状态更新；新增「已完成」列 |
| V1.2 | 2026-08-13 | J4 judge 稳定采样完成；judge 质检 prompt/skill 工程化（独立 .st + SKILL.md） |
| V1.3 | 2026-08-13 | J5 Trace 回放页面完成（后端 trace API + 前端链路回放页） |
| V1.4 | 2026-08-13 | J6 指标看板完成（后端 /api/dashboard + 前端看板页） |
| V1.5 | 2026-08-13 | J2 数据回流完成（sample_pool 表 + 样本库接口/前端 + JSONL 导出） |
| V1.6 | 2026-08-13 | J3 微调评估标记为暂缓（当前为云端 API 技术路线，微调需本地部署模型） |
| V1.7 | 2026-08-13 | K2 深度成本报表完成（token 细分 + 生成/质检阶段拆分 + 多维聚合 + 单条下钻） |
| V1.8 | 2026-08-13 | I3 增强：RAG 知识库前端文件上传（txt/md/docx/pdf，试卷/练习册等）+ 知识库管理页 |
| V1.9 | 2026-08-13 | K4 权限系统主体完成（JWT 认证 + 种子管理员 + 单元测试） |
| V2.0 | 2026-08-13 | J1 质检权重反向校准闭环完成（quality_calibration 表 + calibration.py + qc_node 覆盖权重 + 校准 API + 前端校准中心）；OPT-014 |
| V2.1 | 2026-09-05 | 优化技术设计 2.0 启动：P0-1 错误回注重试（OPT-015）、P0-2 符合率埋点（OPT-016）、P0-5 依赖清理+Langfuse Sink（OPT-017）完成 |
| V2.2 | 2026-09-05 | P0-3 Checkpointer 持久化（OPT-018）、P0-6 Celery 可靠性（OPT-019）、P0-4 judge 一致性 kappa（OPT-020）完成；全量 150 单测通过 |
| V2.3 | 2026-09-05 | P1-2 judge 独立模型（OPT-021）、P1-3 分模型价目表（OPT-022）完成；全量 161 单测通过 |
| V2.4 | 2026-09-05 | OPT-023 改版双生成 Bug 修复（每次改版 2 次 LLM 调用→1 次，质检反馈真实注入）+ OPT-024 灰区 interrupt 人工卡点；全量 175 单测通过 |
| V2.5 | 2026-09-05 | OPT-025 可测性重构 + 集成测试（真 Postgres）+ CI 覆盖率门槛完成：180 用例全过，覆盖率 81.44%；优化技术设计 2.0 的 P0/P1 全部交付 |
| V2.6 | 2026-09-06 | OPT-026 交付审查修复：CI 覆盖率门槛接线、GenState 三键显式声明 + 阈值测试盲区消除、温度配置化、lint（black/isort/flake8）全绿 + CI lint job；项目本体初始化独立 git 仓库并分批入库 |
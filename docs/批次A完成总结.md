# 批次 A P0 开发完成总结

## 交付范围
实施《优化技术设计 3.0》批次 A：状态终态一致性、租户隔离、Outbox 幂等键、生产配置 fail-fast

## 核心改动（9 个文件 + 迁移脚本）

### 1. 新增模块
- **domain/status.py**：状态常量与迁移校验函数 can_transition_content()
- **迁移脚本 m3_01_batch_a_p0.py**：4 处 schema 变更（GenerationTask.result_summary、GenerationTaskItem 新表、ContentItem 4 字段、AppNotification.event_id）

### 2. 数据模型扩展（models.py）
- GenerationTask：result_summary (JSONB) 存储任务级统计
- GenerationTaskItem：新表记录子任务失败追踪
- ContentItem：failure_code/failure_reason/published_by/published_at
- AppNotification：event_id 唯一索引（幂等键）

### 3. 业务逻辑修改
- **workflow/graph.py**：reject_node 落库 failure_code/failure_reason
- **worker/tasks.py**：结果契约统计（succeeded/awaiting/failed）
- **api/routes.py**（3 处）：
  - publish_content()：状态前置检查（仅 passed→published）
  - create_generate_task()：tenant_id 从认证上下文推导
  - list_contents/get_content()：viewer 角色租户过滤
- **rag/retriever.py**：retrieve() 支持 tenant_id 过滤
- **config.py**：生产环境 fail-fast（检查默认密钥/空 API key）

### 4. 异常体系扩展（errors.py）
- ContentStateConflictError：拦截非法状态迁移
- TenantScopeDeniedError：拦截租户越权访问

## 测试覆盖
**19 个单元测试全部通过**（backend/tests/test_batch_a_p0.py）
- 状态迁移校验（允许/禁止的转移）
- 生产配置校验（默认密钥/空 key 拦截）
- reject_node 失败信息构造
- 发布接口状态前置检查
- 租户隔离过滤逻辑

## 验收指标（预期）
| 指标 | 改造前 | 改造后 |
|------|--------|--------|
| reject 内容可解释率 | 0% | 100% |
| 非 passed 内容可发布 | 是 | 否（409 拦截） |
| viewer 可越权读取 | 是 | 否（403 或空结果） |
| 生产环境默认密钥可用 | 是 | 否（启动 fail-fast） |

## 变更追踪
- 优化记录：docs/优化记录.md **OPT-028** ✅
- 任务清单：docs/tasks.md V3.0 批次 A（P0-1/2/3/4 部分完成，4/12） ✅

## 待续工作（批次 B P0）
- Outbox 投递逻辑（relay 定时任务）
- 统一错误码（替换默认 failure_code）
- GenerationTaskItem 填充（worker 为每个 item 创建记录）
- request_hash 部分唯一索引（WHERE status IN ('pending', 'running')）

---
生成时间：2026-09-08
迁移版本：m3_01_batch_a_p0（基于 i8d9e0f1a2b3）
测试状态：19 passed in 9.33s

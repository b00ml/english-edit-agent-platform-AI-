# 批次 B P1 开发计划

## 任务范围（5 项）
基于《优化技术设计 3.0》批次 B：可维护性和运维加固

### 任务清单
1. **P1-1 API/Service/Repository 分层**：拆分 routes.py 上帝模块，保持 URL/响应契约兼容
2. **P1-2 模板输入与输出 Schema 真校验**：按 input_schema 入口校验；保留数组及对象约束；错误不创建任务
3. **P1-3 取消、暂停与批量 item 并发**：取消 API、合作式退出、单 item Celery job、失败分类与退避
4. **P1-4 可观测性与健康检查**：live/ready/dependencies 端点；embedding/queue/workflow Trace；敏感信息脱敏
5. **P1-5 部署、迁移和恢复演练**：Langfuse 数据库初始化、迁移预检查、备份恢复、checkpoint/outbox 重放

## 依赖关系分析
- P1-1 是基础架构重构，影响后续所有服务层开发
- P1-2 依赖 P1-1（Schema 校验应在 Service 层）
- P1-3 部分依赖 P1-1（取消逻辑在 Service 层）
- P1-4 独立（健康检查可并行开发）
- P1-5 独立（部署运维可并行开发）

## 推荐执行顺序
### 批次 B-1（基础架构，串行）
1. **P1-1 分层重构**（风险最高，先做）
2. **P1-2 Schema 校验**（依赖 P1-1 Service 层）

### 批次 B-2（功能增强，可并行）
3. **P1-4 健康检查**（独立，可并行）
4. **P1-5 部署运维**（独立，可并行）

### 批次 B-3（复杂功能，最后）
5. **P1-3 取消与并发**（复杂度高，依赖前置稳定）

## 风险评估
| 任务 | 风险等级 | 风险点 | 缓解措施 |
|------|---------|--------|---------|
| P1-1 | 高 | routes.py 1300+ 行，影响所有端点 | 渐进式重构，保持契约兼容，每层独立测试 |
| P1-2 | 中 | Schema 校验可能拒绝历史合法请求 | 记录拒绝日志，提供兼容模式开关 |
| P1-3 | 高 | 取消逻辑与 LangGraph/Celery 生命周期交互复杂 | 先实现取消 API，后实现合作式退出，分阶段验证 |
| P1-4 | 低 | 健康检查逻辑清晰 | 参考标准实践（k8s probes） |
| P1-5 | 中 | 备份恢复涉及多组件状态 | 先文档化流程，再脚本化，最后演练验证 |

## 本次执行计划
**批次 B-1：P1-1 分层重构**（先做最难的）

### 预期产出
1. 新增模块：
   - ackend/app/services/generation_service.py
   - ackend/app/services/content_service.py
   - ackend/app/services/quality_service.py
   - ackend/app/repositories/（base + 具体表）
2. 修改模块：
   - ackend/app/api/routes.py（瘦身至薄接口层）
3. 测试：
   - 保持现有 API 测试全部通过
   - 新增 Service 层单元测试

### 验收标准
- routes.py 行数降至 500 行以内
- 所有业务逻辑移至 Service 层
- 所有数据访问移至 Repository 层
- 现有 API 契约 100% 向后兼容
- 单元测试覆盖率保持 ≥80%

是否开始 P1-1 分层重构？

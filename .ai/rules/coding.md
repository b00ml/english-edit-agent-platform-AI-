# .ai/rules/coding.md —— 编码规范

## 类型注解（必须）
- 所有函数必须带完整类型注解（参数与返回值），`mypy --strict` 通过。
- 返回可能是 `None` 时用 `Optional[T]` 或 `T | None`；`GenState` 等 dict 用 `TypedDict`。
- 禁止 `Any` 泛滥：仅在动态 Schema 边界（如 `template.output_schema`）使用并加注释说明。

## 异常处理（必须）
- 禁止裸 `except:` / `except Exception:` 吞异常；用自定义异常或精确类型（`ValidationError`、`JSONDecodeError`、`ValueError` 等）。
- 确需捕获宽泛异常（如模型降级、单条失败续跑）时用 `except Exception as exc` 并加 `# noqa: BLE001` 与注释说明意图。
- 自定义异常集中在 `app/errors.py`，命名以 `Error` 结尾。
- 结构化输出重试耗尽、质检所有采样失败应抛出明确异常（含最后一次错误），供上层标记失败。

## 日志与可观测（必须）
- 用结构化日志（`logging` 或 Langfuse），关键调用带 `trace_id` / `task_id` / `item_id`。
- 不使用 `print()` 输出业务日志；日志写 stderr/文件，避免污染流式通道。
- 记录字段：prompt 版本、模型、输入输出（脱敏）、耗时、成本、重试次数。

## 异步与并发
- I/O 密集操作（模型调用、DB 批量）用异步/线程池，避免同步操作阻塞 FastAPI 事件循环。
- Celery worker 内每个子任务独立 `thread_id`，单条失败不中断整体（见 `worker/tasks.py`）。
- 外部 API 调用必须考虑重试与降级，禁止无兜底的单点调用。

## 命名规范
- 变量/函数：`snake_case`；类：`PascalCase`；常量：`UPPER_SNAKE_CASE`。
- 模型字段禁止 `_meta`（Pydantic 冲突），用 `meta`。
- 术语统一：全程用「题型模板 / 生成任务 / 内容条目 / 质检记录 / 模型档案 / 调用链路」，见 `models.py`。

## 工具链（CI 强制）
- 格式：`black`（`line-length 100`）+ `isort`（`profile=black`）。
- 静态检查：`flake8`（`max-line-length 100`，忽略 E501/W503）+ `mypy`。
- 测试：`pytest`，覆盖率 ≥80%，重点覆盖结构化输出、质检加权、路由降级、状态机。
- 提交前必跑：`black . && isort . && flake8 app && mypy app && pytest`。

## 测试
- 核心逻辑必须有单测：`engine/structured_output`、`engine/quality`（加权/兜底）、`engine/router`（降级链）、`workflow/graph`（状态流转与改版 loop）。
- 测试数据用 mock，不真实扣费调用云 API。

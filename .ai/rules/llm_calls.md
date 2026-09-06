# LLM 调用标准化规范

> 适用范围：本项目新增或修改任何**对话式 LLM 调用**（chat completions）时，必须按此规范检查。
> Embedding / 图像 / TTS 等非对话类模型调用不强制 prompt 独立化，但必须带 trace 记录。

---

## 0. 核心原则

### 0.1 Prompt 必独立
任何对话式 LLM 调用的**提示词文本**（system/user/assistant 角色内容）不得硬编码在 `.py` 源码中，必须以独立文本文件存于 `backend/prompts/` 目录，由 `app/prompt_loader.py` 的 `load_prompt()` / `render()` 函数加载与渲染。

### 0.2 Skill 按需配置
Skill 不是给所有 LLM 调用都套一层。Skill 的本质是「**多流程步骤的可复用行为规范**」。

- **需要 Skill 的场景**：该 LLM 调用是一个**可重复的、多步骤的、有明确工作规则的业务动作**，需要稳定的行为约束、Anti-Patterns、执行流程。
- **不需要 Skill 的场景**：该 LLM 调用是**单步纯推理 / 纯格式化 / 纯变换**，或只是通用工程层的包装（如 JSON 强制约束）。

### 0.3 三层校验 + Trace 必录
- 结构化输出必须过 Pydantic 二次校验（代码兜底，不依赖 Prompt 内「请返回 JSON」）
- 每次 LLM 调用必须带 `trace_id`，入库 `trace_log`（含输入输出/耗时/成本）

---

## 1. 判断流程：我现在要加一个 LLM 调用，怎么搞？

```
步骤 A：判断模型类型
    ├─ Embedding / Audio / Vision（非 chat）→ 只需：config 取 key + 记录 trace，无需 prompt/skill
    └─ Chat Completions（对话 LLM）→ 进入步骤 B

步骤 B：Prompt 独立化（必做）
    1. 该调用的 system prompt 是否超过 3 行？ → 是 → 单独 .st
       （即使一行也要独立；但工程层通用的一行提示可共用通用模板，比如 json-enforce.st）
    2. 该调用有 system + user 两个角色吗？ → 都有 → 命名 {scenario}-system.st + {scenario}-user.st
    3. 用户提示包含动态参数吗？ → 是 → 用 {{param}} 占位符，prompt_loader.render() 注入
    4. 需要注入题型/任务专属规则（skill）吗？ → 是 → system st 模板中保留或在代码后置拼接

步骤 C：是否需要 Skill？（决策树）
    ├─ 多流程步骤？（分步思考 → 执行 → 自检？）                ┐
    ├─ 需要严格行为规范？（如评分尺度一致性 / 干扰项设计原则） │→ 需要 Skill
    ├─ 有 Anti-Patterns（易踩坑但规则可描述）？              │
    ├─ 可复用（多题型/多场景共用同一套规范）？               ┘
    └─ 单步纯变换？（翻译 / 格式转换 / 简单分类）
           └─ 不需要 Skill：在 .st 里写清楚指令即可

步骤 D：执行落地
    - 创建/更新 prompts/下的 .st
    - 需要 Skill → 创建 skills/{id}/SKILL.md + skill.meta.yml
    - 代码经 prompt_loader.load_prompt() 加载，再 render({...}) 注入参数
    - 每次调用经 record_trace() 记录 trace_log
```

---

## 2. Skill 判定 Checklist（必须满足 ≥3 条才值得做 Skill）

> 满足不足 3 条的场景，直接写在 .st prompt 里，不要硬造 Skill。

| # | 判定条件 | 判定说明 |
|---|---------|---------|
| 1 | **有明确的「执行流程」** | 超过 1 个操作步骤（先…再…最后…），或需要分阶段思维链 |
| 2 | **有明确的「工作规则」/ Anti-Patterns** | 不能只说「要做好」，必须能列出 ≥3 条「禁止项」或「必做项」 |
| 3 | **有「目标场景」可描述** | 能用一句话明确：此 Skill 用来解决什么问题，在什么业务场景被调用 |
| 4 | **输入/输出契约稳定** | 入参、出参的 schema 明确，不会每次调用都改结构 |
| 5 | **可复用**（≥2 个调用点 / 或 ≥2 个题型共用） | 多题型共享的通用能力（如 judge 质检 / 改版修订 / 题目拆小题） |
| 6 | **需要 Reference 文件** | 需要配套参考资料（如课标摘录、题型示例库、评分 rubric 集）才做得好 |

---

## 3. Prompt 独立化 Checklist

每次新增/修改对话 LLM 调用，对照本表：

### 3.1 命名（强约束）

```
{scenario}-system.st    →  system 角色内容
{scenario}-user.st      →  user 角色内容（含 {{placeholder}} 占位符）
{scenario}.st           →  单角色场景（非 system/user 分离的单提示词场景，尽量少用）
```

`scenario` 命名规则：
- **按题型**：`single_choice`, `cloze`, `reading`（直接对映 `templates/*.yaml` 的 `type_id`）
- **按业务动作**：`judge`（质检）、`revise`（改版）、`summarize`（摘要）
- **按工程层通用能力**：`json-enforce`（JSON 强制约束）、`schema-constraint`（JSON 结构说明包装）

### 3.2 内容（强约束）

- [ ] `system.st` 包含：Role / 目标 / 核心原则 / 输出约束（四要素不必分章节，但内容必须齐全）
- [ ] `user.st` 包含：`{{input_data}}` 形式的参数占位符（占位符名与调用方传参严格一致）
- [ ] 占位符只占动态内容，静态文字不占（避免「模板里就一行 {{all}}」，丧失独立化意义）
- [ ] 如需注入 skill 规范：在 system st 末尾留一个锚点段落，或在调用代码中 `f"{system_prompt}\n\n# {skill_title}\n{skill_md}"` 拼接
- [ ] 输出格式要求放在 system（不是 user），除非格式依赖输入参数

### 3.3 渲染（强约束）

- [ ] 代码经 `prompt_loader.load_prompt("xxx.st")` 读取原始模板
- [ ] 参数注入用 `prompt_loader.render(template, {params…})`，不用手工 `.format()` / f-string
- [ ] `render()` 缺占位符不报错（严格模式由 prompt_loader 决定，默认缺失留空串）

---

## 4. Skill 文件骨架（新建时必含以下段）

```
backend/skills/{skill_id}/
├── SKILL.md           ← 主文档（必含，下文结构）
└── skill.meta.yml     ← 元信息（必含，display + categories）
```

### SKILL.md 结构（必含 6 段）

```
---
name: {skill_id}
description: 一句话描述此 Skill 的业务用途与核心能力。
---

# Overview
- 本 Skill 用来做什么？在哪个业务场景被调用？
- 与相关 Skill 的边界（比如 judge / revise / generate_question 不要互相覆盖职责）。

# 核心目标
- 列出 2-4 条可量化的成功标准（不是口号）。
  例：「稳定性：同一样本多次打分方差 < 1」；「一致性：跨样本同维度尺度一致」

# 执行流程 / Workflow
- 分步骤列：Step 1 …… Step 2 …… Step 3 ……
- 每步写清：输入是什么 → 处理什么 → 输出什么
- ≥2 个步骤才有写此段的意义，<2 步直接进 目标 / 规则即可

# 工作规则
- ≥5 条「必须/严禁」级别的规则，不含糊。
- 每条尽量带判定句（「如果 X 则 Y」），不用「尽量」「最好」之类模糊词。

# Anti-Patterns（禁止事项）
- ≥3 条反模式，每条用 ❌ 标记，说明"为什么不能这么做"。
- 例：❌ 输出 JSON 以外的解释文字 → 调用方无法 parse，导致二次校验失败。

# 输出格式 / 输入输出契约
- 明确输入的字段与含义；
- 明确输出的字段结构（与 prompt st 文件的 Output Format 保持一致）。

# 常见设问句式 / 参考示例（可选）
- 可复用的句式库；
- 可放置 Reference 索引：如 "reference 目录见 docs/references/{skill_id}/"。
```

### skill.meta.yml 结构（必含）

```yaml
displayName: <中文可读名，2-6 字>
display:
  icon: <图标文字>
categories:
  - key: <分类标识大写，如 QUESTION / QUALITY / REVISE>
    label: <中文可读分类>
    priority: CORE   # CORE（核心）或 AUX（辅助）
```

---

## 5. Reference 文件何时需要？

| 需要 Reference 的情况 | 示例 |
|---------------------|------|
| Skill 需要外部知识才能执行正确 | 出题 skill 需要课标摘录、真题范例库、考点分布表 |
| Skill 的判定标准是「对照某文档执行」 | judge skill 有 rubric 细则库（分题型×难度的分档标准） |
| Skill 有大量可复用句式/模板片段库 | generate_question 需要"设问句式库 / 干扰项类型库" |

**存放位置**：`docs/references/{skill_id}/` 下，文件名说明用途（如 `kb_curriculum_grade7.md`）。
在 SKILL.md 的末尾「Reference」段落列出，不要把整份 Reference 塞到 SKILL.md 正文。

---

## 6. 项目内所有 LLM 调用点对照表（审计快照 2026-08-13）

| # | 调用模块 | Prompt 独立化 | Skill | Trace | Pydantic 二次校验 | 状态 |
|---|---------|-------------|-------|-------|-----------------|------|
| 1 | `structured_output.py` 内容生成 | `single_choice/cloze/reading` × system/user.st + `schema-constraint.st` / `json-enforce.st` 通用 | `single_choice`/`cloze`/`reading` 题型 skill + `generate_question` 兜底 | ✅ | ✅ | ✅ 合规 |
| 2 | `quality.py` LLM-as-judge 质检 | `judge-system.st` + `judge-user.st` | `judge`（通用质检评分 Skill） | ✅ | ✅ | ✅ 合规 |
| 3 | `rag/embedding.py` 向量化 | 非对话模型，N/A | N/A | 待补（embedding 未入 trace_log） | N/A | ⚠️ 非对话，仅需补 trace |
| 4 | 改版 revise（graph.py 节点里调用 generate_structured） | 复用 `revise-system/user.st`（题型专属，经 `build_user_prompt` 注入 revise_flag） | 复用题型 skill + 改版规则来自 quality_record | ✅ | ✅ | ✅ 合规（复用生成链路） |

---

## 7. 新增 LLM 调用 Step-by-Step

```
1. 在代码里写好调用前的参数准备，确定 system/user 有哪些固定文本，哪些是动态参数。
2. 确定 scenario 名（按题型 or 按动作 or 按通用能力）。
3. 新建 prompts/{scenario}-system.st + -user.st，把固定文本填入，动态部分用 {{param}}。
4. 用 §2 的 Skill Checklist（≥3 条）判断要不要做 Skill。
   - 要做 → 按 §4 骨架新建 skills/{scenario}/SKILL.md + skill.meta.yml
   - 不做 → 在 system.st 里写清楚工作规则，别硬造 Skill。
5. 写 Reference 判断（§5）：
   - 要 Reference → 在 docs/references/{scenario}/ 放 md，在 SKILL.md 引用
6. 调用代码：load_prompt → render 注入 params → LLM 调用 → Pydantic 校验 → record_trace
7. 补单测：mock LLM 输出，验证
   - prompt 加载正确（含占位符替换后的内容）
   - skill 注入正确（如 system prompt 含 SKILL.md 的标识段）
   - 异常路径（校验失败重试、降级）正确
8. 把本对照表的第 6 节更新，追加新的调用点行。
```

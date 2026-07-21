# Ansich 概念导览

本文面向维护 Ansich 与 DeerFlow 采集适配层的开发者，回答三个问题：系统里有哪些核心概念、它们之间如何关联、哪些数据是原始事实而哪些是可重算判断。设计动机和完整约束见 [ansich-design-document.md](ansich-design-document.md)，分阶段施工细节见 [plans/README.md](plans/README.md)。

## 1. 三层心智模型

Ansich 不把一次 Agent 运行保存成一份不断覆盖的“大 JSON”，而是分成三层：

1. **Observation（事实日志）**：采集到的不可变事件。它回答“在什么时间，哪个 producer 声称发生了什么”。
2. **Entity / Relation / typed projection（事实读模型）**：从 Observation 幂等投影出的实体、关系和专用索引。它回答“如何高效查询 Task、Step、ToolCall、上下文和谱系”。
3. **Belief / Assertion / Alert（可重算判断）**：assessor 在明确 watermark 下，根据事实产生的带版本结论。它回答“当前证据支持什么判断，以及判断为何成立”。

```text
DeerFlow runtime
    │  fail-open capture
    ▼
Observation + payload ── projection job ──► typed entity / relation / usage
                                                │
                                                ▼
                                      versioned assessor
                                                │
                                                ▼
                                      Belief / Alert episode
```

Observation 是重放依据，typed projection 和 Belief 都可以从它重建。任何读模型都不得反过来成为事实来源。

## 2. 执行实体

### Task

一次具有独立生命周期、预算和归属边界的 Agent 工作单元。lead Agent 的一次 Run 是 root Task；每次真实 subagent 委派是独立 child Task。Task 通过 `parent_task` 和 `task_ancestor` 关系组成树，而不是把所有子 Agent 活动塞回 root Task。

- 身份：稳定 UUID；不使用线程名、用户输入或路径作为主键。
- 生命周期：`created → running → completed | failed | interrupted`，由 Observation 推导。
- 载荷：摘要、控制状态和预算进入 typed projection；原始内容仍由 payload 分层管理。
- 实现：`backend/packages/ansich/ansich/task.py`、`backend/packages/harness/deerflow/ansich/persistence/sql.py`。

### AgentRelease

Task 开始执行时实际使用的 Agent 行为配置快照。它由有效 model、prompt hash、tool catalog、middleware/policy manifest 和 runtime build 共同形成确定性 fingerprint。requested model alias 不属于行为身份，effective provider model 属于。

- 不可变：同一个 release identity 不能绑定不同 manifest。
- 安全：manifest 先做字段 allowlist、secret 清洗和二线 credential 模式校验；不保存 prompt 正文和凭证。
- 关系：Task 通过 `executed_by` 绑定 release。
- 实现：`backend/packages/ansich/ansich/release/`。

### Step

Agent 决策循环中的一个逻辑步骤。一个 Step 可以经历多个 LLM attempt，但只有成功关闭 Step 的 attempt 是 effective attempt。Step 不等于单次模型请求，也不等于 ToolCall。

- 顺序：`step_seq` 在 Task 内严格递增。
- 系统操作：summarization 等非模型业务操作也可以作为 `actor_kind=system_operation` 的 Step/operation 暴露。
- 实现：`backend/packages/ansich/ansich/step.py`。

### LLM attempt

Step 中一次实际 provider 请求。它引用本次请求使用的 ContextSnapshot，并保留 requested/responded/failed 证据。重试产生新 attempt，不覆盖旧 attempt。

- 顺序：`attempt_no` 在 Step 内递增。
- effective：由 Step 关闭事实决定，而不是“最后一个 attempt”猜测。
- provider model report：属于 attempt evidence，用于 configuration drift 判断，不改变 AgentRelease 身份。

### ToolCall

模型发出的一个工具调用意图及其执行生命周期。它把“issued intent”“是否开始执行”“raw result”“model-visible result”分开保存。

- 身份：Task/Step 内稳定 call sequence 与 provider call id 共同解析，不依赖工具结果文本。
- 状态：authorization、execution、visible result 是带 evidence 的读模型，而不是一个混合 status 字段。
- 内容：参数只保存受控 preview/hash；raw 与 visible result 指向独立 ContentBlock。
- 实现：`backend/packages/ansich/ansich/tool.py`。

## 3. 上下文与内容谱系

### ContentBlock

一段可独立寻址、去重和建立派生关系的内容，例如 user input、assistant message、tool raw result、tool visible result、summary、memory 或 skill 注入。ContentBlock 描述内容身份和元数据，payload 是否可读由 retention 与敏感级别决定。

- `content_hash` 是内容身份辅助信息，不是原文替代品。
- raw、sanitized、truncated、externalized、coalesced 等版本是不同 block，并用 derivation 关系连接。
- 实现：`backend/packages/ansich/ansich/content.py`。

### ContextSnapshot

某次 LLM attempt 真正可见的有序上下文清单。成员顺序具有语义，因此使用 `(snapshot_id, ordinal)` 专用表，而不是无序 JSON 数组或普通 Relation。

- snapshot 记录完整成员 inventory、缺失成员和 completeness。
- ContextSnapshot 指向 ContentBlock；它不复制 block payload。
- trim/compression 产生新 snapshot 或新 block，旧快照保持不可变。
- 实现：`backend/packages/ansich/ansich/context.py`、`backend/packages/ansich/ansich/compression.py`。

### Relation

Entity 之间的有证据有向边，例如 `within_scope`、`parent_task`、`task_ancestor`、`executed_by` 和内容 `derived_from`。关系表同时提供 subject→object 与 object→subject 索引；关系 evidence 单独保存，因此重放和晚到证据不会丢失来源。

Relation 适合表达稀疏、多值、可正反向遍历的语义边；严格有序成员、频繁查询字段和具有自身属性的领域对象使用专用 typed table。

## 4. 事实、判断与告警

### Observation

Collector 接收的不可变 envelope，包含 kind、发生/记录时间、Task/subject identity、producer、因果引用和经过敏感字段校验的 payload。`obs_id` 与 `source_event_id` 支持幂等写入。

- fail-open：Ansich 写入或投影失败不能改变 Agent 的业务结果。
- append-only：纠正通过新 Observation/Assertion 表达，不原地改写旧事实。
- payload 分层：envelope 和可查询结构长期保留；大体积或敏感 payload 可独立 retention。
- 实现：`backend/packages/ansich/ansich/contracts.py`、`service.py`。

### Belief / Assertion

assessor 对某个 subject 字段在 `as_of` watermark 下作出的版本化判断。Assertion 保存 value、assessor/source version、config hash、authority/fidelity 和 evidence，不冒充 Observation。

- 同一状态未变化时不重复追加断言。
- 新 evidence 或 resolver 版本可以产生新 assertion；历史判断仍可审计。
- `unknown` 是一等值，不能被缺行或默认 false 替代。
- 实现：`backend/packages/ansich/ansich/assessment/`。

### Alert

由已支持的结构化 condition 进入 episode 状态机形成的运维事件。Alert 具有 episode、evidence、severity 和 acknowledge/dismiss 工作流；它不是 Task 控制状态，也不能替代 Assertion。

- 同一 alert key 的 condition 持续存在时更新当前 episode，而非每秒新增告警。
- condition 消失后 episode resolved；之后再次出现创建下一 episode。
- 实现：`backend/packages/ansich/ansich/alert.py`。

## 5. 资源、预算与聚合

### Usage contribution

从一个源 Observation 规范化出的单维度增量。幂等键为 `(source_obs_id, dimension)`；rollup 只消费 contribution，不重新解析原始 Observation。

- local usage：仅当前 Task 的贡献。
- inclusive usage：当前 Task 加所有 descendant Task 的贡献。
- source breakdown：保留贡献来自当前 Task 还是哪个 child Task，便于解释聚合值。
- 实现：`backend/packages/ansich/ansich/usage.py`。

### Budget

Task admission 时解析出的 effective limit，以及运行期间对应维度的 usage/breach 判断。absolute budget 在 terminal 时进行最后一次评估并保留 breach assertion；terminal Task 不再进入每秒周期扫描。

Budget 是 policy limit，Usage 是事实贡献，breach 是判断，三者不能合并成同一个可变计数器。

## 6. 投影基础设施

### Projection

把 Observation 转换成 typed rows、relations、usage contributions 和 assessor jobs 的确定性逻辑。projector 以明确 version 运行，并且必须满足幂等、可重放、晚到证据可收敛。

### Projection job

持久化的待执行工作项，记录 observation/watermark、projector、attempt、状态和 last error。依赖未到达时可以有界重试；超过等待上限进入 failed，operator 可诊断并重试。failed job 会使 health 进入 degraded，但不回滚 Agent 业务执行。

## 7. Scope、Authorization 与 Effect

这组三个概念从 Phase 9 开始形成 Safety Audit 数据链，三者必须分开建模。

### Scope

一个稳定的归属、执行或资源边界。v1 scope kind 包括 `owner`、`thread`、`workspace`、`sandbox`、`authorization`、`external_origin`。Task 可以同时位于多个 Scope；`within_scope` relation 的 role 说明关系含义，例如 owner、conversation、execution workspace 或 auth context。

- 路径和外部标识先规范化为受控 label 与 stable ref hash，不把 tenant credential 或敏感绝对路径当 ID。
- child Task 继承 Scope 必须有 relation evidence，不能只在读取时隐式猜测。
- Scope 是多值关系，不在 Task 上增加单个 `scope_id`。

### AuthorizationSnapshot

Tool decision/execution 前当时有效授权事实的不可变快照，包含 principal/resource scopes、policy identity/hash、effective permissions、decision（allowed/denied/unknown）、reason 和 evidence。

- 保存 effective permission，不保存 JWT、cookie、API key 或原始 Authorization header。
- provider 只返回 bool 时标记 `details_available=false`，不补猜权限。
- Ansich 采集失败不改变 DeerFlow 的授权决定；DeerFlow deny 仍必须阻止工具执行。

### Effect

工具可能、意图或实际造成的外部影响。`phase` 分为 `potential`、`intended`、`observed`；effect class 包括 filesystem read/write/delete、process execute、network read、external write、permission change、child task spawn 和 unknown。

- policy allowed 不证明 observed effect 发生。
- 工具返回 success 或 shell exit code 0 不证明“无副作用”。
- bash/MCP 无足够 instrumentation 时必须记录 unknown/coverage，而不是推断具体 effect 或显示 “No side effects”。
- target 只保存 fingerprint 和受控 preview；raw target 由独立、强审计 payload 读取控制。

`scope-safety` assessor 使用 intent、AuthorizationSnapshot 和 observed Effect 产生 policy denial、attempted violation、realized violation 或 unverified effect。Tool 文本不能单独支持 realized violation。

## 8. 修改概念时的同步规则

新增或改变领域概念时，同一个 change set 至少同步：

1. 本文中的定义、边界和关系；
2. `ansich-design-document.md` 的协议/世界模型；
3. 对应 Phase 计划与测试矩阵；
4. `contracts.py` 的 Observation/subject contract；
5. SQLite migration、SQL typed projection 与 replay 测试；
6. API DTO 和前端类型，确保 `unknown`、completeness 与 evidence 不在传输中丢失。

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

一个稳定的归属、执行或资源边界。v1 scope kind 包括 `owner`、`thread`、`workspace`、`sandbox`、`authorization`、`external_origin`、`host`。Task 可以同时位于多个 Scope；`within_scope` relation 的 role 说明关系含义，例如 owner、conversation、execution workspace、auth context 或 `host_environment`。`host` kind 用 hostname 的 stable ref hash 规范化身份（不把敏感绝对路径/凭证当 ID）；单机部署下是一个固定 Scope，供环境观测的宿主共享信号（磁盘余量、PSI）挂载，Phase 11 预留的 `observability_degradation`/`projection_failure` process-subject 映射与本节共享同一个 `host` Scope 机制，不另造。

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

## 8. 评估与语义 Belief

这组概念从 Phase 10 开始，把“运行完成”和“语义正确”彻底分开：完成不是通过，没有评估也不是通过。

### Evaluation（`evaluation.recorded`）

一次外部评估结果的不可变 Observation。单次 evaluation 不创建 Evaluation Entity，只有将来出现多步骤、可分派、可关闭的 review workflow 时才提升为 Entity。subject 可以是 `task`、`step`、`tool_call`、`content_block` 或 `agent_release`；`evaluation_kind` 为 `user_feedback`、`developer_annotation`、`benchmark_assertion`、`unit_test`、`llm_judge`；`dimension` 为 `correctness`、`completeness`、`relevance`、`safety`、`efficiency`、`earliest_erroneous_step` 或 `custom`。

- 载荷：verdict 与 score 至少有一个；score 必须带 `{min,max,higher_is_better}` scale，裸数字不可比因而被拒绝。`expected`、`actual`、`rationale` 是正文，只留在 Observation payload，查询投影不复制。
- fidelity：`hard` 只允许 `benchmark_assertion`/`unit_test`，且必须带 suite、suite_version、case_id；来自 admin 本身不构成 hard。`earliest_erroneous_step` 必须 subject 为 Task 且在 `actual` 指名属于该 Task 的 Step，不做内容相似度猜测。
- 幂等：suite 绑定的评估以 `(suite, suite_version, case_id, run_id, dimension)` 为 replay 身份，刻意不使用 API 的 `Idempotency-Key`；其余入口由调用方 key 派生 source event ID。
- 入口：Gateway admin API、feedback 适配器与 benchmark 导入都调用同一个 core validator，不在路由里拼 Observation；feedback 主写成功后才 best-effort 发 evaluation，Ansich 失败不改变原 API 结果，也不能反过来掩盖 feedback 主写失败。
- 实现：`backend/packages/ansich/ansich/evaluation.py`、`backend/app/gateway/routers/ansich.py`、`backend/app/gateway/feedback_evaluation.py`。

### quality Belief

`quality.<dimension>` 是 Assertion 的 field，不是 Observation，也不是 Task 控制状态。`evaluation-projector@1` 把五个具名维度的评估投影成 `quality.<dimension>` assertion；`custom` 只进索引不产生断言，`earliest_erroneous_step` 断言的是 Step 指针而不是质量 verdict。

- authority 映射：suite 绑定且 `hard` → `deterministic`；其余 suite 绑定 → `configured_rule`；显式 human override 的 developer annotation → `human_override`；普通开发者标注与用户反馈 → `soft_human`；LLM judge → `automated`。
- fidelity 取自 payload；Observation envelope 自身的 `fidelity_class` 恒为 `hard`，描述的是“这条记录被采集到”这一事实，不是判断强度。
- 未评估：五个具名维度总是返回完整 Belief 结构，`value={"status":"unassessed"}`、`source={name:"none",version:"1"}`、authority/fidelity 为 `unknown`、无 evidence。Task completed 不能推出 pass。
- 冲突：相冲突的 pass/fail assertion 全部保留，读接口返回 selected assertion 与 `conflicting_assertion_count`。
- `quality` 与 `behavior` 是两回事：一次 correctness fail 不使 Task 变成 runaway，一个 runaway Task 也可能得到 correct 结果，两个 Belief 同时存在。
- 实现：`backend/packages/harness/deerflow/ansich/persistence/sql.py` 的 `evaluation-projector@1`。

### Resolver `ansich-default@2`

优先级阶梯为 `human_override > deterministic > configured_rule > soft_human > automated`；同一 class 内按 `as_of`、`asserted_at`、`assertion_id` 取最新。因为新增了 `soft_human` 这一 precedence 语义，所以升版而不是原地改 v1。

- `ansich-default@1.0.0` 逐字保留并可按版本显式选择，历史 resolution 仍可重放；v1 不认识 `soft_human`，遇到该 class 直接报错而不是静默降级。
- 实现：`backend/packages/ansich/ansich/belief/resolver.py`。

### 评估查询投影

两张可删除、可按 projector version 重放的读模型，都不是 canonical record：

- `ansich_evaluation_index`：每条 evaluation Observation 一行，只存元数据（verdict/score/scale、assessor、authority/fidelity、cohort、suite/case、occurred_at）。索引为 `(subject_type, subject_id, dimension, occurred_at)`、`(suite_id, suite_version, case_id)` 与 `(task_id, occurred_at)`。
- `ansich_release_quality_stats`：以 `(release_id, cohort_key, dimension)` 为复合主键的聚合格。每个绑定该 release 的 Task 只贡献一个样本，取自它当前的 `quality.<dimension>` Belief，因此被保留的冲突 assertion 不会重复计数；聚合格按格加锁重算，避免并发投影丢失更新。
- 迁移：`0023_ansich_evaluations`。实现：同 `sql.py`。

### Cohort 可比性

release 之间的语义质量比较只在同一 cohort 内进行。以下条件全部满足才给出 observed delta：cohort key 非空且相同、dimension 相同、score scale 相同（含 `higher_is_better` 极性）、两侧样本数都达到 `ansich.evaluation_min_cohort_samples`、没有未解释的观测丢失。

- 条件不满足时返回 `comparison_status="not_comparable"` 和机器可读 reason：`no_shared_cohort`、`scale_mismatch`、`insufficient_samples`、`observability_loss`（按此优先级），而不是用所有生产 Task 平均分强行比较。
- 未声明 cohort 的评估聚合在 `""` 哨兵下；它是样本清单而不是比较总体，两个 release 上出现同一个哨兵不代表共享 suite、版本或 case 集合。
- v1 只报告 observed delta（`right - left`，两侧都有均分时用均分，否则用 pass rate），不做统计显著性结论。
- 实现：`backend/packages/ansich/ansich/quality.py`。

## 9. 修改概念时的同步规则

新增或改变领域概念时，同一个 change set 至少同步：

1. 本文中的定义、边界和关系；
2. `ansich-design-document.md` 的协议/世界模型；
3. 对应 Phase 计划与测试矩阵；
4. `contracts.py` 的 Observation/subject contract；
5. SQLite migration、SQL typed projection 与 replay 测试；
6. API DTO 和前端类型，确保 `unknown`、completeness 与 evidence 不在传输中丢失。

## 10. 环境观测

Ansich 的第二类证据来源：执行环境的 OS 级观测信号（fd、io、内存、磁盘、压力），与 DeerFlow runtime 采集（决策、attempt、ToolCall、heartbeat、预算等）并列，但语义分级更严格，因为不同 provider 的“环境”物理形态不同（AIO 容器是长驻环境，local 每条 bash 是短命子进程）。

### `environment.sampled`（Observation）

`subject_type = "scope"`，`subject_id` 是 sandbox Scope 或 host Scope 的 scope_id；`fidelity_class` 依惯例恒为 `hard`（描述“采到了这条样本”这一事实），判断强度由 assessor 依据 payload 的 `environment_scope`/`coverage` 决定。payload 强制字段：`environment_scope`、`coverage`、`window`、`provider`、`metrics`、`tool_call_id`（仅 `per_command` 填写）。

**硬规则一：`environment_scope` 决定语义等级，全链路（投影、assessor、API、前端）不可丢失：**

- `container`：沙箱隔离环境的真实存量（仅 AIO 容器 cgroup/fd）；
- `process_group`：单条命令进程组的消耗快照——测不到存量，fd 值是该命令峰值，不是“沙箱当前打开数”；
- `host_shared`：与宿主机所有进程共享的信号（磁盘余量、PSI），永远不冒充沙箱指标。

缺失的 metric 维度不写零，直接不出现（沿用 usage 的“未报告 ≠ 0”纪律）；`coverage = "uninstrumented"` 仅允许空 `metrics`、`sample_count = 0`，每 run 至多发一条声明。

### 采集器

`AnsichEnvironmentProbe`（`deerflow/ansich/probes/environment.py`）完全仿照 `AnsichTaskHeartbeat`：worker 在 `task.started` 后与 heartbeat 并排启动，按 provider 分派——AIO 读容器 cgroup 指标（`container`/`continuous`），local 采宿主磁盘余量与 PSI（`host_shared`/`continuous`，同时声明 host 与 sandbox 两个 Scope），其余 provider 只在 run 启动时发一条 `uninstrumented` 声明后自行停止。每次采样经 `asyncio.to_thread` 下放（`/proc`、docker 读取是阻塞 IO，必须过 blocking-io 门禁）；`stop()` 有界（默认 2 秒），避免拖慢 Task 终态收尾。

local sandbox 还有按命令采样：`LocalSandbox` 在命令运行期间用 ansich 无关的轻量 `ProcessGroupSampler`（`deerflow/sandbox/telemetry.py`）后台线程枚举进程组成员，累计 io/fd 峰值；结果经 `asyncio.to_thread` 边界的显式 `Context` 回传（`sandbox/tools.py::_run_sync_tool_after_async_sandbox_init`），由 Ansich tool probe 链发出 `process_group/per_command` 观测，携带权威 `tool_call_id`。sandbox 层不 import ansich。

### 投影与评估

`environment-projector@1` 注册在 `task-safety` 之后（挂在其建立的 Scope 实体上），产出三张读模型（migration `0026_ansich_environment`）：`ansich_environment_coverage`（per-Scope 覆盖态）、`ansich_environment_state`（每 `(scope_id, environment_scope, metric)` 一行的现状行，先锁后读，含 `consecutive_growth_count` 趋势字段）、`ansich_tool_env_samples`（每 `tool_call_id` 至多一行，供 ToolCall 详情读；无外键，不参与依赖等待投影）。

`environment-pressure@1` assessor 挂进现有周期 operations 评估循环，产出两类结论：`environment_pressure:<metric>`（fd/disk/PSI 越阈，authority=`configured_rule`）与 `environment_leak:fd_open`（container + continuous 下 fd 连续增长的“suspected”判断）。Alert evidence 附采样时刻该 Scope 内 `running` 的 Task 列表，字段名 `possibly_affected_task_ids`——**硬规则二：这是时间相关性，不是因果**，措辞与建模都不得声称因果，同 `possible_exposure` 的纪律。

**硬规则三：缺数据永远是 unknown，不是 ok。** run 活跃但超过 3× 采样间隔无样本，或 `coverage = uninstrumented`，assessor 一律降级为 `unknown`；环境评估绝不写 Task 控制状态。

**硬规则四：`per_command` 数据永远不喂泄漏规则。** 进程组快照测不到存量，`environment_leak` 规则的输入被硬限制为 `container` + `continuous`；v1 也不从单命令样本产生任何 Alert——episode 状态机建模持续 condition，单命令尖峰是点事件，硬塞会产生秒开秒关的 episode 噪音；per_command 的价值只在读侧（ToolCall 详情、Task 时间线），点事件告警通道待真实使用证据后另行设计。

### 读侧

`GET /api/ansich/tasks/{task_id}/environment` 沿 `within_scope` 找 sandbox/host Scope，返回每 scope 的现状行（metrics + coverage + environment_scope）、当前 `environment_pressure`/`environment_leak` Belief（unknown 完整下发）、以及活跃/历史环境 Alert 摘要；两个新 `AlertType`（`environment_pressure`、`environment_leak_suspected`）进公共 filter，list/detail/acknowledge/dismiss 复用现有机制。ToolCall 详情读模型加 additive 可空字段 `environment_sample`。前端 Task 详情“运行环境”面板每 scope 一张卡，`environment_scope` 徽标（容器实测/进程组快照/宿主共享）+ coverage 徽标（含“未观测”态），unknown 显式渲染为“未知”，不用空白或绿色。

- 实现：`backend/packages/ansich/ansich/environment.py`（契约/assessor）、`backend/packages/harness/deerflow/ansich/probes/environment.py`（连续 probe）、`backend/packages/harness/deerflow/sandbox/telemetry.py`（按命令 sampler）、`backend/packages/harness/deerflow/ansich/persistence/sql.py`（`environment-projector@1`）、`backend/app/gateway/routers/ansich.py`。

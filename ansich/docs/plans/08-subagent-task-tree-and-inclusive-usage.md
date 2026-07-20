# Phase 8 — 子 Agent Task 树与 inclusive usage

## 1. 交付目标

本阶段把 DeerFlow `task` Tool委派提升为独立 child Task。child拥有自己的 AgentRelease、Step、attempt、ToolCall、heartbeat和 local usage；parent通过 spawning Step 与 child关联。Operator可以查看 Task树及 parent inclusive usage，且原始 token/Tool consumption不会双写。

DeerFlow v1子 Agent不允许继续递归委派，但数据模型和查询必须防御历史/未来多层树，不能把层级硬编码为一层。

## 2. Child Task identity 与 context传播

修改 `tools/builtins/task_tool.py` 和 `subagents/executor.py`。当 parent ToolCall通过基本参数校验、准备启动 executor时：

1. 从 `AnsichToolContext`取得 parent task、spawning step、ToolCall。
2. 分配 child `task_id`，source kind=`deerflow_subagent`，source ID使用 executor稳定 task ID。
3. 发 child `task.created`，payload 含 parent/spawning Step/ToolCall IDs 和 subagent logical name；Structural projector 由该 Observation 建立 `spawned` relation，不新增含义重叠的 `subagent.spawned` kind。
4. 构造显式 `AnsichExecutionContext`传给 `SubagentExecutor`，不是依赖 parent ContextVar偶然复制。
5. child真正开始/terminal时分别发 lifecycle Observation；timeout/cancel/failure严格映射。

如果 child context初始化失败，subagent仍按原路径运行；parent Ansich ToolCall标 observability degraded，而不是阻止委派。若 executor在 child ID分配后没有启动，child control证据停在 created，reconciliation用明确启动失败原因关闭为 failed/unknown，不伪造 running。

## 3. Subagent Agent probes

Subagent构造必须使用与 lead相同的 Decision/Attempt/Tool probe factory，只改变 `actor_kind=subagent` 和 child task context。现有 `task_started/task_running/subagent.step` RunJournal事件继续保留给聊天 UI；Ansich不从这些紧凑事件反推完整 Step，而在 subagent内部直接采集真实模型边界。

child AgentRelease由实际 subagent effective model、prompt、Tools、skills、policy生成，不能继承 parent release。Scope继承在 Phase 9细化；本阶段至少关联 owner/thread/workspace/sandbox refs并标 inheritance source。

subagent result作为 parent ToolCall raw/visible ContentBlock，同时 producer关系指向 child Task terminal output，形成 child result → parent visible context的 lineage。

## 4. Task tree 关系

将 `spawned` 从低频 generic relation升级为 typed表：

- `ansich_task_spawns(parent_task_id, spawning_step_id, spawning_tool_call_id, child_task_id, established_obs_id)`；`child_task_id`唯一，一个 child不能有两个 parent。
- `ansich_task_ancestry(ancestor_task_id, descendant_task_id, depth, established_obs_id)`；唯一 `(ancestor_task_id, descendant_task_id)`。

插入 direct spawn时，projector读取 parent所有 ancestors，写 self-free transitive closure。写前检查 child不是 parent ancestor；检测 cycle时拒绝关系、记录 projection error并把相关 Task observability标 degraded。数据库 FK保证 Step/Tool属于 parent Task。

`follows_up` 与 `spawned`保持不同关系：用户下一消息是新 top-level Task follow-up，不是 child。

## 5. Local 与 inclusive usage

原始 `budget.consumed` 永远写 source child Task。Phase 5 `ansich_usage_contributions`扩展为：

```text
aggregate_task_id
source_task_id
dimension
source_obs_id
delta
as_of
```

local row只含 `aggregate_task_id=source_task_id`。每条 child contribution通过 ancestry复制成 ancestor contribution，但仍保留相同 `source_task_id/source_obs_id`；唯一 `(aggregate_task_id, source_task_id, dimension, source_obs_id)`阻止重放双计。

`ansich_task_usage`生成两类 summary：local只汇总 source=self；inclusive汇总该 Task及所有 descendants。late spawn关系到达时必须 backfill child既有 contributions；late child usage到达时正常 fan-out ancestors。删除/重放 projections可得相同总数。

Budget比较按 TaskBudget aggregation_scope选择 local/inclusive。parent的 inclusive硬限制是否真正 enforcement取决于 DeerFlow runtime；若 DeerFlow只在各 child局部限制，则 parent inclusive budget只能 `enforcement=false`。

## 6. Heartbeat 和终态语义

parent等待 child时 parent outer heartbeat继续；child有独立 heartbeat。child terminal不自动关闭 parent Task或 parent ToolCall，后者还要经过 Tool result middleware。parent interrupt时：

- 能确认 cancellation传播到 child：child terminal=`interrupted/cancelled` hard evidence；
- 只发出 parent cancel但无法确认线程终止：child control保留 running/unknown，打开 liveness evidence gap；
- child后来回报 terminal：按 occurred_at修复。

Task tree API需要同时展示 parent/child各自 observability health，不能用 parent健康覆盖 child丢失。

## 7. API

新增：

```text
GET /api/ansich/tasks/{task_id}/tree?direction=both&depth=
GET /api/ansich/tasks/{task_id}/children
GET /api/ansich/tasks/{task_id}/usage?scope=local|inclusive
```

tree返回节点、spawn edge、spawning Step/Tool、release、control/heartbeat Beliefs、local/inclusive usage、projection status。默认 depth=4，硬上限32；达到上限返回 truncated。

Task list允许 `root_only=true`，active operations中 parent行显示 child active count和 inclusive usage。API不得把 child Steps平铺到 parent Step列表；开发者必须通过 tree进入 child。

## 8. 前端

Task Overview增加可折叠 Task tree；每个 node显示 actor/release、状态、当前 Step、local/inclusive token和健康。点击 child切换同一 Task detail shell中的 task_id，不复制 parent timeline。

Budget tab提供 local/inclusive切换并标明贡献来源。可展开 contribution按 source Task聚合，帮助解释 parent inclusive超限。Lineage中 parent Tool result显示 producer child Task链接。

## 9. TDD 测试矩阵

- context propagation：async executor、thread executor、缺 context fail-open、多 parent并发隔离。
- identity/relation：一个 parent多个 child、child唯一 parent、cycle拒绝、late relation、未来两层树。
- probes：child真实 Step/attempt/Tool，RunJournal紧凑事件不重复投影。
- release/scope：child有效配置独立、owner/thread继承 evidence。
- usage：local/inclusive、重复 Observation、late spawn backfill、late usage、两层 rollup、重放无双计。
- cancellation：child completed/failed/timed out、parent interrupt确认/不确认、late terminal。
- API/UI：depth/truncated、root_only、child navigation、contribution解释、各节点 degraded。
- fail-open：child Ansich context创建/写入故障不改变 `task_tool`原返回或错误。

## 10. 完成条件

- 每次实际 subagent委派产生一个 child Task和一条可追证据的 spawn relation。
- child的 Step、Tool、release和 local usage不混入 parent自身记录。
- parent inclusive usage等于 self + descendants，原始 consumption只出现一次。
- late/duplicate spawn与usage重放不双计。
- parent取消但 child终态不确定时保持 unknown，不伪造 cancelled。

## 11. 落地说明（2026-07-20）

### 11.1 Runtime identity、context 与 release

- `task_tool.py` 在委派参数通过校验后，以 parent Task、spawning Step、spawning ToolCall 和 executor stable task ID 构造确定性 child Task 身份，并记录 `source_kind=deerflow_subagent` 的 `task.created`。重复 attempt 不会产生第二个 child。
- child 使用独立 `AnsichExecutionContext`，由 `task_tool` 显式传入 `SubagentExecutor`；executor 把该 context 直接放入实际 subagent runtime，而不依赖 ContextVar 在线程或协程之间偶然复制。
- child 启动后拥有独立 lifecycle、heartbeat、Step、attempt、ToolCall 和实际 assembly 产生的 AgentRelease。lead worker 同时改为消费显式 `LeadAgentAssembly(graph, descriptor)`；`make_lead_agent()` 的 graph-only 返回和自定义 factory graph attribute 只作为兼容边界。
- context 创建、Observation 写入或 release 绑定失败均 fail-open，不改变委派业务结果。若 child ID 已分配但 executor 构造/启动失败，探针以 `failure_reason=executor_start_failed` 关闭 child，避免永久残留在 `created`。

### 11.2 Typed tree projection

- migration `0019_ansich_task_tree_usage` 新增 `ansich_task_spawns` 与 `ansich_task_ancestry`。direct spawn 同时验证 spawning Step/Tool 确属 parent；`child_task_id` 唯一约束保证一个 child 只有一个 parent。
- projector 写入 self-free transitive closure，并在写前拒绝 cycle 或第二 parent；失败保留 projection error，并按既有通道降低 observability health。
- `direction=ancestors|descendants|both` 查询从 typed closure 构造 bounded tree；`both` 返回祖先与后代的并集，不把共同 parent 下的 sibling 误当作当前 Task 的后代。默认深度与 32 层硬上限按计划执行。

### 11.3 Source-aware usage 与重放

- `ansich_usage_contributions` 的身份扩展为 `(aggregate_task_id, source_task_id, dimension, source_obs_id)`。原始 Observation 仍只属于实际消耗 Task；ancestor fan-out 是可删除、可重放的投影，不复制原始事实。
- self contribution 同时刷新 local 与 inclusive summary；descendant contribution 只刷新 ancestor 的 inclusive summary。usage 先到时正常沿 ancestry fan-out，spawn 后到时从 descendant 既有 self contribution 做 backfill，两种顺序得到相同结果。
- token、attempt、Step、Tool 与 `child_tasks_spawned` 使用累加语义。heartbeat 的 `wall_time_ms` 是同一 source Task 的累计水位，因此先按 source 取最大值，再把 parent 与各 descendant 的水位相加，避免按心跳次数膨胀。
- Budget assessor 按 `aggregation_scope` 读取同一套 contribution：local 只选 source=self，inclusive 读取全部 source；usage API 同时返回按 source Task 分组的解释数据。
- migration 将历史 self contribution 映射到新的 aggregate/source 身份，为每个已有 local usage 生成对应 inclusive summary，并清空旧 active-task materialization，使其按新 JSON contract 重建。downgrade 先移除 fan-out/inclusive 派生行，再恢复旧列语义。

### 11.4 API 与 Operator Lens

- Gateway 新增 children、bounded tree、`usage?scope=local|inclusive`，并给 Task list 增加 `root_only`。active rows 返回 `active_child_count` 与 inclusive Usage；Task tree node 返回 release、control/heartbeat、当前 Step、local/inclusive Usage 和节点自身 health。
- Operations 历史列表使用 `root_only=true`，避免 child 同时出现在顶层历史和 parent tree。Task Overview 显示可折叠树；点击 child 进入该 child 自己的详情页，不把 child Timeline/Steps 平铺进 parent。
- Budget 面板支持 local/inclusive 切换并展示 source Task breakdown；Context lineage 中，带 server-owned producer Entity marker 的 parent-visible Tool result 可链接到 child Task。Gateway 丢弃客户端伪造 marker，attempt adapter 在 provider 调用前剥离内部 marker。

### 11.5 验证边界

- 后端回归覆盖确定性 identity、显式 context、child release/lifecycle、fail-open、唯一 parent/cycle、两层 closure、late spawn/late usage/replay、wall-time source 水位、SQLite 迁移与 PostgreSQL DDL 编译、tree/children/usage/root-only API。
- 前端单测覆盖 scoped usage 请求和 root-only 历史参数；Ansich E2E fixture 覆盖 tree 展开、child 导航、inclusive source breakdown 与 producer child link。
- 真实 PostgreSQL 升级矩阵、关闭 Ansich 的性能对比和生产 paper drill 仍按总计划作为最终生产就绪门禁，不阻塞本地 Phase 8 纵向切片。

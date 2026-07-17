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

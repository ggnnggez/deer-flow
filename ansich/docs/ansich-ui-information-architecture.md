# Ansich Developer/Operator UI Information Architecture

状态：Proposal  
日期：2026-07-22  
适用范围：Ansich Operations 与 Task Detail 管理员界面

## 1. 背景与目标

当前 Ansich UI 已经能够查询 Task、Belief、Alert、Step、ToolCall、Context、AgentRelease、Scope、Authorization、Effect、Usage、Budget 与 Projection Health，但展示方式仍接近“投影表浏览器”：大量字段、卡片和 Tab 处于相同视觉层级，观测者需要自行跨页面拼接事实，才能判断是否需要处理以及 Agent 为什么做出某个动作。

本设计不减少证据，也不改变 Ansich 的世界模型。目标是重新组织信息，使默认界面优先回答以下问题：

1. 是否存在需要立即处理的异常？
2. Agent 当前在做什么，已经持续多久？
3. 哪个结构化信号触发了关注，影响范围是什么？
4. 当前判断由哪些 Context、LLM Attempt、Authorization 与 Effect 证据支持？
5. 当需要审计时，如何到达完整 Observation、Lineage、Hash 与 Payload？

第一版仍面向 Developer 与 Operator，不尝试生成普通用户所需的 Task 进度百分比或业务结果摘要。

## 2. 当前信息架构的问题

### 2.1 Operations 页面

- Projection Health 在页面顶部平铺十余项指标，健康信号和故障信号同权。
- Running Task 行同时展示 Task、当前动作、Control、Heartbeat、Usage、Budget 与 Projection，缺少唯一的主信号。
- Alert 与 Task 分处不同 Tab，Operator 需要自行建立“告警属于哪个运行、当前还在做什么”的关联。
- 正常 Task 与异常 Task 使用接近相同的视觉密度，无法快速扫描待处理项。
- Task UUID 与 Run ID 占据主要识别位置，但缺少更适合人类辨认的受控名称。

### 2.2 Task Detail 页面

- Header 主要展示完整 Task UUID 与 source，无法在首屏形成诊断结论。
- Overview、Timeline、Steps、Budgets、Agent Release、Scopes & Effects、Context & Lineage 七个 Tab 平级；因果链被切断。
- Current Belief 默认展示 resolver、config hash、evidence UUID 与 JSON，判断层被审计层覆盖。
- Step、ToolCall、Context 与 Effect 分开呈现，Developer 必须手工回答“模型看到了什么 → 选择了什么 → 策略如何处理 → 实际发生了什么”。
- Raw ID、Hash 与 provenance 过早出现，重要状态反而缺乏视觉焦点。

### 2.3 Alert Detail

- 详情首先展示 metadata grid，而不是事件摘要、影响和可采取动作。
- rule version、config hash、episode、evidence count 等审计属性与严重程度、当前状态处于同一层级。
- Alert subject 可能是 Task 或 ToolCall；缺少稳定的 Task 聚合与定位信息时，跳转容易失去上下文。

## 3. 观察者问题与页面职责

Ansich 不通过同一页面同时满足所有观察者，而是让路由本身表达观察视角：

| 页面 | 主要观察者 | 首要问题 | 默认信息密度 |
| --- | --- | --- | --- |
| Operations | Operator | 哪些运行需要处理？ | 低，异常优先 |
| Task Summary | Operator / Developer | 这个 Task 当前怎么了？ | 中，诊断摘要 |
| Decision Trace | Developer | 这一步基于什么证据选择了这个动作？ | 中，因果链 |
| Resources & Safety | Operator / Developer | 使用了什么资源，是否越界或超限？ | 中，约束与 Effect |
| Evidence | Developer / Auditor | 原始事实和投影依据是什么？ | 高，显式展开 |

“为什么做出决策”只能表述为可观测的 decision evidence：有效 Context、模型请求与响应、Tool intent、Authorization、执行与可见结果。UI 不推断或宣称展示模型不可观测的隐藏思维过程。

## 4. 渐进式披露模型

### 4.1 四个信息层级

| 层级 | 目标阅读时间 | 回答的问题 | 内容 |
| --- | --- | --- | --- |
| L0 态势 | 5 秒 | 有没有需要立即关注的事？ | Attention 数量、Critical 数量、运行数、观测系统状态 |
| L1 诊断 | 30 秒 | 单个 Task 怎么了？ | 当前动作、主要信号、持续时间、影响范围、建议入口 |
| L2 解释 | 2 分钟 | 为什么得出该判断？ | Context → LLM → Tool → Authorization → Effect → Result |
| L3 审计 | 按需 | 原始证据是什么？ | Observation、UUID、Hash、resolver、payload、lineage |

默认展开 L0 与 L1。L2 按 Step 或 Alert 展开。L3 只能通过 `Technical evidence`、`View raw payload` 或 `Lineage` 等显式动作进入。

### 4.2 不删除，只降级

- UUID 默认显示短 ID，完整值由 Copy 按钮或 Technical details 提供。
- Hash 默认不出现；当需要比对 release、args、policy 或 content identity 时显示。
- resolver、producer、config hash 与 evidence UUID 收进折叠区。
- Raw ContentBlock 和 Tool result 继续按需获取，禁止进入轮询响应或预取缓存。
- Unknown、missing、partial、degraded 不能通过折叠变成“看起来正常”。

## 5. Operations 页面设计

### 5.1 页面结构

```text
Ansich Operations                         Data healthy · lag 1.2s [System details]

┌────────────────┬────────────────┬────────────────┬────────────────┐
│ 3 Needs attention │ 12 Running  │ 2 Degraded     │ 1 Critical     │
└────────────────┴────────────────┴────────────────┴────────────────┘

Needs attention                                             [Filters]

 CRITICAL  Inclusive budget exceeded
 general-purpose · Task a82f… · currently bash · running 2m 14s
 118k / 100k tokens · 2 active child Tasks
                                           [Inspect] [Interrupt]

 WARNING   Heartbeat stale
 lead-agent · Task c91d… · last evidence 47s ago
                                           [Inspect]

Running normally (9)                                      [Expand]
History                                                    [Open]
```

### 5.2 顶部态势栏

固定展示四个有明确含义的聚合值：

- Needs attention：存在 open warning/critical Alert，或 observability degraded 的 Task 数。
- Running：当前 control=`running` 的 root Task 数。
- Degraded：Task observability degraded 或证据完整性降级的数量。
- Critical：最高严重度为 critical 且未 resolved/dismissed 的 Task 数。

Projection Health 不再平铺所有指标。默认只显示：

```text
Data healthy · lag 1.2s
```

当 health 为 degraded/failed、failed jobs 大于零、存在 lost range 或 storage unavailable 时，状态提升为页面级横幅。完整 queue、水位、snapshot 与失败 job 信息进入 `System details` Drawer。

横幅的口径按页面分层，避免与本页无关的告警反复打断操作：

- Operations 页保持全局口径：全部 failed jobs、全部 lost range 与 projection status。
- Task 详情页只统计本 Task 自己的 failed jobs（按 `task` 过滤的有界列表，取满一页时显示为 `50+`）与本 Task 自己的 lost range；`task_id` 为 null 的未归属丢失只属于系统口径，不计入任何 Task。其它 Task 造成的全局 degraded 不再在此提升为横幅。
- 例外是系统级硬故障（`storage_available=false`，或 status 为 failed/stopped）：此时 Task 页自身的数据同样来自这份投影，不可信，必须显示一条明确标注为「系统级」的横幅，而不能声称本任务数据完整（永不虚构确定性）。

横幅中的失败作业数在任何需要关注的状态下都可点击，直接打开对应口径的失败 Job 列表（Task 页已按本 Task 过滤，Operations 页为全局列表）。本 Task 的失败作业计数尚未返回、或请求失败时按未知处理：未知不等于失败，既不提升为横幅也不计入徽标，但会把绿色的「本任务数据完整」替换为中性的「本任务失败计数暂不可用」——未作答同样不等于没有失败。收起快照中的未知计数按不对称规则比较：计数由已知变为未知不算恶化（未知不是更大的数），但快照本身记录的是未知时，说明操作者当时并未确认任何失败计数，此后计数解析出真实失败即属于新证据，横幅重新展开；解析为 0 比已确认的状态更好，保持收起。

横幅可被操作者收起：收起后横幅整体隐藏，页面标题行右侧出现一个琥珀色 `⚠ N` 徽标（真实 `button`，`aria-label` 携带当前状态），点击即可恢复横幅——信息只是被折叠，不会从无障碍树中消失。收起状态按口径分别保存在 sessionStorage（system 与 `task:<id>` 互不影响），记录的是收起当时的 failed jobs / lost 数量与 status 快照。当失败数或丢失数上升、或 status 恶化（healthy < degraded < failed/stopped）时，记录作废、横幅自动重新展开；恢复到无需关注时同样清除记录，使下一次异常仍以完整横幅开始——但只认真实计数背书的恢复：计数未知时不清除记录，否则重新加载页面的等待窗口（sessionStorage 仍在、查询缓存已空）就会把收起状态悄悄丢掉，其寿命将取决于请求竞速。系统级硬故障不提供收起按钮。

### 5.3 Attention Queue

Operations 的默认主区域是 Attention Queue，而不是所有 Running Task。

每项只展示：

- severity 与 primary signal；
- 受控 Task identity；
- current activity；
- signal age / task duration；
- 一项最相关的影响指标；
- `Inspect` 与当前允许的 operator action。

排序由后端版本化规则决定，禁止前端自行推断：

1. critical open Alert；
2. realized scope violation / hard budget exceeded；
3. heartbeat stale / observability degraded；
4. warning open Alert；
5. evidence unknown 或 partial；
6. healthy running。

同级按 `primary_signal.as_of DESC`、`task_id` 稳定排序。

### 5.4 Running 与 History

Running normally 默认折叠，只显示数量。展开后使用紧凑列表，每行仅保留：

- Task identity；
- 当前 Step/Tool；
- duration；
- heartbeat；
- 一个 resource headline；
- observability 状态。

History 默认展示：

- 可读 Task identity；
- terminal outcome；
- duration；
- terminal time；
- 是否曾出现 warning/critical；
- 是否存在 evidence gap。

完整 source、UUID、Usage 维度等进入行展开区。

### 5.5 身份展示

在正式引入安全的 `task_label` 前，Task identity 使用以下降级顺序：

1. `agent_name/subagent_name`；
2. `source_kind`；
3. `owner_id` 或 thread 的受控短标签；
4. Task ID 前 8 位。

不得直接使用原始用户 Prompt 作为 Task 标题。若未来增加 `request_summary`，必须具有独立的 sanitization、长度限制和访问策略。

## 6. Task Detail 页面设计

### 6.1 Sticky Task Header

```text
< Operations

general-purpose · deerflow_run · a82f…                 RUNNING · 2m 31s
owner-1 · 3 child Tasks                       [Copy Task ID] [Technical details]

┌──────────────────────────────────────────────────────────────────┐
│ CRITICAL  Inclusive token budget exceeded by 18%                 │
│ First observed 42s ago · still active          [Evidence] [Stop] │
└──────────────────────────────────────────────────────────────────┘
```

Header 默认展示：

- 人类可识别的 actor/source；
- 短 Task ID；
- control 与 duration；
- child Task 数；
- highest-priority open signal；
- 可用 operator action。

完整 UUID、source_id、thread_id、owner_id、projection watermark 等进入 Technical details。

### 6.2 首屏诊断摘要

首屏使用三个语义区块，而不是 Belief metadata grid：

```text
Current activity          Why attention is needed       Impact
bash · Step 7             Budget exceeded               Parent + 2 children
dwell 18s                 Heartbeat fresh               118k / 100k tokens
```

三个区块的内容都必须来源于后端 read model：

- Current activity：current Step/Tool 与 dwell；
- Primary signal：Alert/Belief/observability 中选出的唯一主信号；
- Impact：受影响的 Task、Scope、Budget 或 Effect 摘要。

没有证据时显示 `Insufficient evidence`，不能使用绿色正常状态占位。

### 6.3 页面导航

现有七个平级 Tab 收敛为四个问题导向入口：

#### Summary

- Task header 与 primary signal；
- 诊断摘要；
- open Alerts；
- 最近一条 causal trace；
- Task tree 摘要；
- resource headline。

#### Decision trace

- Logical Step 列表；
- 每个 Step 的有效 Context 摘要；
- LLM Attempt 与 retry；
- model output 中的 Tool choice；
- Tool authorization/execution/result chain；
- 从当前 Task 跳转 child Task。

完整 Context inventory 和 lineage 由 Step 内的 `Inspect context` 打开，不再要求用户先离开 Step 页面再寻找相同 step_id。

#### Resources & safety

- local/inclusive Usage；
- Budget headline 与异常项；
- Task Scopes；
- Tool intent → authorization → observed effect；
- policy denial、attempted/realized scope violation、unverified effect。

正常、未配置与证据不足的 Budget 默认折叠；warning/exceeded 默认展开。

#### Evidence

- Observation Timeline；
- 完整 Context & Lineage；
- Compression inventory；
- Agent Release 与 typed diff；
- Projection/assessor diagnostics；
- raw/visible payload 按需读取。

### 6.4 Causal Trace

Causal Trace 是 Developer 视角的核心组件：

```text
Context 23 items
   → LLM attempt #1 · model gpt-x
   → selected bash
   → authorization allowed
   → process_execute observed
   → internal effects unverified
   → result visible to model
```

每一段必须可定位到结构化实体：

| 节点 | 数据来源 | 点击行为 |
| --- | --- | --- |
| Context | effective ContextSnapshot | 打开有序 inventory |
| LLM attempt | LlmAttempt | 展开 latency、usage、provider model |
| Tool choice | ToolCall issued | 展开受控 args preview/hash |
| Authorization | AuthorizationSnapshot | 展开 policy/version/reason |
| Effect | ToolEffect | 展开 phase/scope/fidelity |
| Result | raw/visible Tool result | 显式按需读取 payload |

连线表示已记录的 observation/causation/relation，不表示模型“注意到了”某个内容，也不补推隐含因果。

### 6.5 Step 渐进式披露

折叠状态：

```text
Step 7 · Acting · 1.8s
Context 23 items → model selected bash → execution returned
1 ToolCall · effect coverage partial                         [Expand]
```

第一次展开：

- LLM attempts；
- ToolCall accountability chain；
- Authorization 与 Effect 摘要；
- Context completeness；
- raw/visible result 是否可用。

第二次展开 `Technical evidence`：

- step/tool/attempt UUID；
- Observation IDs；
- args/content/policy/config hash；
- producer/resolver version；
- causation/lineage edge；
- payload access。

### 6.6 Alert Detail 顺序

Alert Dialog 调整为以下顺序：

1. 一句话事件摘要；
2. severity、workflow 与是否仍 active；
3. 影响对象与 current activity；
4. 可用 operator actions；
5. “为什么触发”结构化证据；
6. Observation timeline；
7. Rule/version/config hash/workflow history 折叠区。

Operator action 继续使用服务端 workflow version 与 idempotency key。Interrupt 必须明确表示停止执行并保留 checkpoint，不得描述为 pause。

## 7. 视觉语义

### 7.1 颜色

| 语义 | 颜色 | 使用边界 |
| --- | --- | --- |
| Immediate action | Red | critical、realized violation、hard limit exceeded |
| Investigation | Amber | warning、stale、degraded、partial coverage |
| Current activity | Blue | running、当前 Step/Tool |
| Unknown | Neutral/gray dashed | insufficient evidence、unknown、missing |
| Healthy | Small green accent | 仅状态标识，不铺满卡片 |

颜色必须同时配合文本与图标，不作为唯一状态表达。

### 7.2 Typography 与密度

- 状态结论使用正常 UI 字体；UUID、Hash、版本号使用 monospace。
- 相对时间作为主文本，绝对时间放 tooltip 或详情。
- 正常列表行高度控制在 52–64 px；Attention item 可使用 88–112 px。
- 首屏最多同时出现一个红色主信号，避免多处竞争。
- JSON 不在 Summary 默认显示；结构化 key/value 优先于 `<pre>`。

### 7.3 Unknown 与证据完整性

必须区分：

- `unknown`：系统没有足够证据得出结论；
- `partial`：已知部分事实，但观测范围不完整；
- `degraded`：观测通道或投影发生故障；
- `unconfigured`：没有配置该规则或 Budget；
- `none observed`：只有在 probe 明确声明覆盖范围 complete 时才能使用。

空数组或缺失行不得自动显示为 healthy/no effect。

## 8. 后端 Read Model 契约

仅依赖现有细粒度 API 可以实现第一轮布局，但 Attention Queue 与 Task 诊断摘要不应长期由浏览器聚合。否则会产生 N+1、轮询闪烁、subject 映射错误以及前后端规则漂移。

### 8.1 Operations Overview

```text
GET /api/ansich/operations/overview
```

建议响应：

```json
{
  "as_of": "2026-07-22T10:00:00Z",
  "counts": {
    "running": 12,
    "needs_attention": 3,
    "degraded": 2,
    "critical": 1
  },
  "attention_items": [
    {
      "task_id": "...",
      "display_identity": {
        "actor": "general-purpose",
        "source_kind": "deerflow_subagent",
        "short_id": "a82f1234"
      },
      "control": "running",
      "current_activity": {
        "kind": "tool",
        "label": "bash",
        "step_seq": 7,
        "duration_ms": 18000
      },
      "primary_signal": {
        "signal_kind": "alert",
        "signal_id": "...",
        "alert_type": "budget_exceeded",
        "severity": "critical",
        "label": "Inclusive token budget exceeded",
        "as_of": "2026-07-22T09:59:18Z"
      },
      "impact": {
        "label": "118k / 100k tokens",
        "affected_task_count": 3
      },
      "observability_status": "healthy",
      "available_actions": ["interrupt", "rollback"]
    }
  ],
  "system_health": {
    "status": "healthy",
    "lag_ms": 1200,
    "failed_jobs": 0,
    "lost_observation_count": 0
  },
  "projection_status": {}
}
```

`primary_signal` 必须由版本化 resolver 选择，并保留其 source assertion/alert evidence。前端只能展示和导航，不能重新排序信号权威性。

### 8.2 Task Diagnostic Summary

```text
GET /api/ansich/tasks/{task_id}/diagnostic-summary
```

建议响应：

```json
{
  "task_id": "...",
  "display_identity": {},
  "control": {},
  "duration_ms": 151000,
  "current_activity": {},
  "primary_signal": {},
  "open_alerts": [],
  "impact": {},
  "resource_headline": {
    "budget_state": "exceeded",
    "usage_scope": "inclusive",
    "active_child_count": 2
  },
  "evidence_quality": {
    "value": "partial",
    "reason_codes": ["unverified_effect"]
  },
  "latest_trace": {
    "step_id": "...",
    "step_seq": 7,
    "nodes": []
  },
  "projection_status": {}
}
```

Task Alert 必须通过 typed relation 映射。Safety Alert 的 subject 可能是 ToolCall，Operations summary 不得把 ToolCall ID 当作 Task ID。

### 8.3 缓存与轮询

- Operations overview 在存在 running Task 时沿用 5 秒轮询；无运行时退避。
- Task diagnostic summary 在 Task running 时轮询，terminal 后停止。
- Attention item 与 Task summary 共享 `as_of`，避免多个查询产生撕裂式首屏。
- raw payload、full release manifest、lineage traversal 与 Alert evidence 不参与自动轮询。
- ETag 应覆盖语义内容，不因内部 refresh timestamp 无变化而失效。

## 9. 前端组件拆分

建议新增或重构以下组件：

```text
components/workspace/ansich/
├── operations-command-bar.tsx
├── attention-queue.tsx
├── attention-task-card.tsx
├── compact-task-list.tsx
├── system-health-drawer.tsx
├── task-hero.tsx
├── task-diagnostic-strip.tsx
├── causal-trace.tsx
├── progressive-step-card.tsx
├── resource-safety-panel.tsx
└── technical-evidence.tsx
```

现有组件的调整：

- `projection-health.tsx`：拆为 compact status 与 detail drawer。
- `active-task-row.tsx`：改为正常运行的紧凑行，不再承载所有诊断字段。
- `alert-panel.tsx`：列表进入 Attention Queue；详情按行动优先顺序重排。
- `step-explorer.tsx`：Step 与 ToolCall 使用两级 accordion，并嵌入 Context/Authorization/Effect 摘要。
- `scope-effects-panel.tsx` 与 `budget-panel.tsx`：合并进 Resources & Safety，共享异常优先排序。
- `observation-timeline.tsx`、`lineage-explorer.tsx`、`agent-release-panel.tsx`：归入 Evidence，保留 lazy/no-store 规则。

所有主要视图状态写入 URL query：

```text
?view=decision&step=7&tool_call=...&evidence=authorization
```

这样 Alert、Task tree 与 Operations 可以稳定深链到相同证据位置。

## 10. 响应式与可访问性

- Desktop：Attention Queue 主列 + 可选 system summary 侧栏；Task trace 使用横向因果链。
- Tablet：摘要卡单列，因果链允许水平滚动但提供表格 fallback。
- Mobile：阶段链改为纵向，操作按钮固定在 Alert/Task card 底部。
- 所有状态使用 icon + text + accessible label。
- Accordion、Drawer、Dialog 支持键盘导航和 focus return。
- 动态轮询更新不得抢占焦点；状态变化通过适度的 live region 提示，不重复播报全部列表。
- 图形化因果链必须提供等价的有序列表/表格。

## 11. 实施阶段

### UI-1：前端信息重排

不增加后端字段，先完成：

- Projection Health compact + drawer；
- Task UUID 降级展示；
- Task Detail hero 与诊断区布局；
- Step 两级 accordion；
- Alert Detail 行动优先重排；
- Technical evidence 折叠；
- 四个问题导向入口。

该阶段可以复用现有 API，但不得为了首屏对每个 Task 发起额外查询。

### UI-2：聚合 Read Model

- 新增 operations overview；
- 新增 task diagnostic summary；
- 实现版本化 primary-signal resolver；
- 修正 Alert subject → Task 聚合；
- 增加稳定 ETag 与 polling 测试。

### UI-3：Causal Trace 与深链

- 构建 Context → LLM → Tool → Authorization → Effect → Result trace；
- 支持 Step/Tool/Evidence URL deep link；
- Alert 与 Task tree 定位到具体 trace node；
- 保留图形/表格双视图。

### UI-4：验收与密度调优

- 真实高并发 Task 数据试用；
- 键盘与移动端验收；
- 视觉回归与 E2E；
- 记录定位异常所需时间与点击数。

## 12. 测试与验收标准

### 12.1 语义测试

- critical 必须排在 warning/healthy 之前；
- unknown/partial/degraded 不得显示为 healthy；
- resolved/dismissed Alert 不进入 active Attention count；
- ToolCall subject 的 Safety Alert 能定位到 owning Task；
- primary signal 变化由后端 resolver version 控制；
- terminal Task 停止自动轮询，但保留 terminal overshoot 与历史 Alert。

### 12.2 UI 测试

- 首屏不出现完整 UUID、Hash 或 JSON；
- 一次点击可从 Attention item 到达 Task Summary；
- 两次以内可到达触发 Alert 的 Step/ToolCall；
- Raw payload 未点击前不发起网络请求；
- Projection healthy 时不展示完整指标墙；
- Projection degraded 时页面级提示不可被普通 Task card 淹没；
- mobile 与 keyboard 能完成 Inspect、Evidence、Acknowledge 与 Interrupt 流程。

### 12.3 成功指标

- Operator 在 5 秒内能指出是否存在需要处理的 Task；
- Developer 在 30 秒内能指出当前 Step、Tool、Authorization 与 Effect 状态；
- 从 Operations 到结构化 evidence 不超过 3 次交互；
- 正常运行场景首屏技术字段数量减少至少 60%；
- 所有现有 raw evidence 仍可到达，且 lazy/no-store 边界不退化。

## 13. 明确不做

- 不展示或推断隐藏 chain-of-thought。
- 不从 Step 数、Tool 数或 Token 使用量推导普通用户进度百分比。
- 不用空 effect rows 推断“无副作用”。
- 不在浏览器实现新的 Alert/Belief 权威性规则。
- 不把 raw Prompt、credential、绝对 host path 或未脱敏 payload 放入 summary read model。
- 不因重新布局而放宽 Ansich 的管理员访问控制。


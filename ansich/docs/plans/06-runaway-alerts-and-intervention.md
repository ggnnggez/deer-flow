# Phase 6 — 失控告警与干预

## 1. 交付目标

本阶段实现第一个完整的“Observation → Assessor → Belief Assertion → Resolver → Alert → Operator action”闭环。系统可以基于绝对预算突破和完全相同的动作签名重复判断 runaway；普通 Tool 高频只能产生 frequency Alert，不能自动把 Task 标记为 runaway。

Operator 可以查看证据、acknowledge/dismiss Alert，并调用 DeerFlow 已有 interrupt/rollback。Ansich 不新增 pause/resume 或 force terminate 语义。

## 2. Assessor 接口和版本

独立 core 新增：

```text
assessment/base.py
assessment/absolute_limit.py
assessment/action_repetition.py
assessment/tool_frequency.py
belief/resolver.py
alerts/episodes.py
```

每个 assessor 声明 `name`、semantic version、input Observation kinds、config hash 和输出 field/value/fidelity。它只追加 Belief Assertions，不直接更新 Current Belief 或 Alert。

初始 resolver `ansich-default@1`：control state 仍选最新有效 hard lifecycle；semantic state 按 explicit human override > deterministic hard evaluation > configured rule > soft assessor，同一 class 内按 `as_of`、`asserted_at`、稳定 assertion ID 排序。Current Belief 保存 selected assertion、resolver name/version，保留原 assessor source。

改变阈值、canonicalization 或 precedence 必须增加 assessor/resolver version；重放旧 Observation 时不能静默覆盖旧版本结果。

## 3. Exact action signature

ToolCall signature：

```text
sha256(canonical_json({"tool": tool_name, "args": secret_filtered_args}))
```

Step signature 是该 Step 所有 ToolCall signature 的排序多重集合；保留重复调用次数，忽略并行完成顺序。canonical JSON 递归排序 object keys、保留 array 顺序、规范数字/Unicode，不包含 provider ID、时间、Ansich ID 或 redaction 前 secret。

`action-repetition@1` 在同一 Task 的连续 Agent Steps 窗口内比较签名。只有达到配置的完全相同窗口才输出 `Task.behavior=runaway` rule assertion。只要任一 Step signature 不同就重置连续计数；不做模糊文本/参数相似度判断。

配置：

```yaml
ansich:
  assessors:
    exact_repetition_window: 5
    tool_frequency_window_seconds: 300
    tool_frequency_threshold: 30
```

绝对 Step/token/wall-time 使用 Phase 5 effective budget。enforcement=false shadow threshold 的 assertion/Alert 必须标 `shadow=true`。

## 4. Belief 与证据表

扩展 `ansich_belief_assertions`：subject、field name、typed value JSON、as_of、asserted_at、assessor name/version/config hash、fidelity、confidence nullable。`ansich_belief_evidence(assertion_id, obs_id, evidence_role, ordinal)` 作为唯一证据来源，禁止只在 assertion JSON 存 ID 数组。

`ansich_current_beliefs` 存 selected assertion 和 resolver，projection 可全部删除重建。Resolver 处理晚到 Observation 时，旧 `as_of` assertion 不得因 committed 晚而覆盖新证据。

Transitions 只用于具有生命周期的状态；`Task.behavior` 的 assertion 变化不伪造 control Transition。需要展示历史时按 assertions 的 as_of 查询。

## 5. Alert episode 模型

创建：

- `ansich_alerts(entity_id, alert_key, episode, alert_type, subject_id, source_assertion_id, opened_at, resolved_at, resolution_reason, workflow_state, workflow_version)`。
- `ansich_alert_evidence(alert_id, obs_id, role, ordinal)`。
- `ansich_alert_read_model`，面向 operations list。

`alert_key = sha256(alert_type + subject_id + rule_name + stable_condition_key)`；同一条件未 resolved 时重复确认更新 evidence/as_of，不创建新 Alert。条件恢复后 resolved；后来再次发生，`episode + 1` 创建新实体。`acknowledged`/`dismissed` 是 workflow observation，不删除 underlying assertion。

Alert 类型：budget warning/exceeded、exact repetition、tool frequency、heartbeat missing、long dwell、observability degradation、projection failure。Tool frequency assessor只开 `tool_frequency` Alert，绝不写 behavior=runaway。

Dismiss 写 `operator.alert_dismissed`，可附结构化 reason；若用户明确标注误报，可另写 human semantic assertion，但该行为必须是显式字段，不能把所有 dismiss 都当作 Task on_track。

## 6. Operator actions

新增：

```text
POST /api/ansich/operations/alerts/{alert_id}/acknowledge
POST /api/ansich/operations/alerts/{alert_id}/dismiss
POST /api/ansich/tasks/{task_id}/actions/interrupt
POST /api/ansich/tasks/{task_id}/actions/rollback
```

所有 action 先 `require_admin_user`，再验证 Ansich Task 的 source run/thread 与 DeerFlow RunManager 实际记录一致。不能信任客户端传入 run ID。使用现有 Run cancel/rollback service 实现，不复制 checkpoint 逻辑。

调用序列：写 `operator.action_requested` → 调 DeerFlow → 写 succeeded/failed。为了 fail-open 和审计安全的平衡：Ansich 写 requested 失败不阻止用户调用已有 DeerFlow action，但响应必须返回 `audit_status=degraded`；DeerFlow action 的成功与否只以 RunManager 结果为准。重复 request 带 idempotency key，避免网络重试执行两次 rollback。

interrupt 只说明请求中断并保留当前 checkpoint；rollback 使用 DeerFlow 已有 pre-Run checkpoint 语义。若当前状态不支持 action，返回 409 和 hard control evidence；不得把 interrupt 文案写成 pause。

Alert ack/dismiss 使用 `workflow_version` 乐观并发；冲突返回 409 并返回当前 Alert。

## 7. Assessor 调度

Projector 完成相关 Step/usage/heartbeat Observation 后 enqueue assessor job，而不是在 API 查询时临时推断。job key 为 `(subject_id, assessor_name, assessor_version, evidence_watermark)`；重复投递幂等。

heartbeat/long dwell 需要 wall-clock scheduler，每次扫描只为超过阈值的 running Task生成 rule evaluation Observation；当前 wall clock参与 assertion `asserted_at`，evidence仍引用最后 heartbeat/transition。Task terminal 后 resolve operational Alert，但 absolute-limit事实 assertion 保留。

poison assessor job 走 Phase 1 projection error；Phase 11 完成租约和隔离。

## 8. API 与 UI

新增 operations alerts list/detail，支持 type/state/Task/time/severity filters。Alert detail必须返回 rule version/config、source Belief、ordered evidence Observation、当前 Task Beliefs、workflow history 和可用 actions。

Operations 页面加入 Alerts 区域；Task Overview 显示当前 behavior Belief。UI 在证据中清楚区分：

- `runaway`：exact repetition 或绝对规则支持；
- `high tool frequency`：仅运维信号；
- `heartbeat missing`：liveness rule，不是 hard failed；
- `shadow`：未被 DeerFlow enforcement 使用。

ack/dismiss/interrupt/rollback 均需要确认对话框、pending 防重复和结果 toast；失败后保留服务器返回的 evidence，不做乐观假成功。

## 9. TDD 测试矩阵

- signature canonicalization：key 顺序、Unicode、数字、array、parallel multiset、secret redaction、重复项。
- runaway：连续相同、窗口前变化重置、并行顺序变化仍相同、参数变化不算 exact。
- frequency：30 个不同查询只开 frequency Alert，不写 runaway assertion。
- absolute limits：warning/hard、overshoot、shadow、Task terminal 后事实保留。
- resolver：hard/rule/soft/human precedence、同级 as_of、晚到 assertion、version replay。
- episodes：重复确认去重、recovery resolve、再次发生新 episode、ack/dismiss并发冲突。
- actions：admin、source mapping、unsupported state、idempotency、RunManager success/failure、audit write failure。
- UI：证据分类、shadow 文案、确认流、409刷新、action failure。
- fail-open/fail-safe：assessor/Alert 故障不改变 DeerFlow runtime guard；现有 loop/token enforcement仍执行。

## 10. 完成条件

- artificial exact repetition和 absolute breach在配置窗口内产生 evidence-backed Belief 与 Alert。
- 改变参数的高频 Tool 不会自动标 runaway。
- Alert confirmation、resolve、recurrence 按 episode 幂等工作。
- resolver 输出可追到原 assertion、resolver version和所有 supporting Observations。
- Operator actions只代理 DeerFlow 已支持语义，并有 requested/succeeded/failed 审计结果。

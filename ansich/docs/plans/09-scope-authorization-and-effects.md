# Phase 9 — Scope、授权与副作用审计

## 实现状态（2026-07-21）

已形成可运行的本地纵向切片：P7-L1 二线 credential validator 已接入 release resolution；Scope 使用 stable external-ref hash、受控 label、parent 与带 role/evidence 的 `within_scope`；AuthorizationSnapshot、permission/scope membership、ToolCall binding 与 potential/intended/observed Effect 均有严格领域契约和 `0020_ansich_scope_safety` typed SQL 投影。DeerFlow Tool middleware 在 callable boundary 区分 allow/deny，并以 fail-open 方式记录 effect；`scope-safety@1.0.0` 在严格 observation watermark 下维护四类 present/cleared conclusion，attempted/realized/unverified 复用 Alert episode。管理员 API 与 Task 详情 “Scopes & effects” 页签已落地，unknown coverage 不会显示为无副作用。

本地验收已覆盖 SQLite upgrade/downgrade/replay、PostgreSQL DDL 编译、领域/SQL/API/probe 回归（353 项）以及前端 lint/typecheck 与单元测试（667 项）。真实 PostgreSQL 升级矩阵、关闭 Ansich 的开销基准和生产 paper drill 仍是最终生产就绪门禁；MCP 显式 effect metadata、外部写 adapter 的更细 resource canonicalization 以及 raw target 强审计读取继续按 Phase 11 加固边界推进。

## 1. 交付目标

本阶段完成 D4 Safety Audit所需的数据链：一个 Task/Step/ToolCall处于哪些 Scope；Tool发出了什么 effect intent；当时有效权限是什么；授权层允许/拒绝/未知；实际观测到了什么副作用。

授权与副作用严格分开。policy allow不证明 effect发生；Tool返回成功不证明没有额外副作用；policy deny不产生 executed effect，但可以支持 attempted scope violation。

## 2. Scope 类型与关系

扩展 Phase 1 Scope：

```text
owner
thread
workspace
sandbox
authorization
external_origin
```

`ansich_scopes`包含 `scope_kind`、stable external ref hash、display label、parent scope、created obs。敏感绝对路径/tenant credential不直接作为 ID；workspace/sandbox path先规范化到允许展示的 logical root，必要时只存 hash和受控 label。

`within_scope` relation增加 role：`owner`、`conversation`、`execution_workspace`、`sandbox_boundary`、`auth_context`、`trigger_origin`。Task admission记录所有已知 Scopes；Step继承 Task scopes需要 evidence relation，ToolCall可在授权时增加更窄 scope。

Scope是多值，禁止在 Task表新增单个 `scope_id`替代关系。

## 3. AuthorizationSnapshot

在 Tool decision/execution前，从 `deerflow.authz.adapter/provider`、sandbox policy、MCP/tool allowlist和run context构造不可变 snapshot：

```text
authorization_snapshot_id
tool_call_id
principal_scope_ids[]
policy_id/version/hash
effective_permissions[]
resource_scope_refs[]
decision              // allowed | denied | unknown
reason_codes[]
evaluated_at
evidence_obs_ids[]
```

snapshot保存 effective权限，不保存JWT、cookie、API key或原始Authorization header。permissions按 stable resource/action canonicalize；若 provider只返回bool而无细节，保存 allowed/denied和`details_available=false`，不能补猜权限列表。

Observation顺序：`scope.snapshotted` → `authorization.evaluated` → `authorization.allowed/denied/unknown`。若 authorization middleware在 Ansich probe之前短路，Phase 3 intent仍存在，reconciliation写 decision unknown而不是 allowed。

## 4. Effect 模型

effect class固定为：

```text
filesystem_read
filesystem_write
filesystem_delete
process_execute
network_read
external_write
permission_change
child_task_spawn
unknown
```

每个 effect还包含 phase=`potential|intended|observed`、resource scope、target fingerprint/受控 preview、result metadata和 fidelity。Tool schema/catalog可声明 potential effects；Tool args parser生成 intended effects；sandbox/MCP/tool instrumentation生成 observed effects。

采集优先级：

- DeerFlow file tools与sandbox audit middleware：记录规范化 sandbox-relative path、operation、result；禁止越界绝对路径泄漏。
- bash：记录 process_execute observed；命令内部文件/网络 effect若无 syscall tracing则为 unknown，exit code 0不等于无其他 effect。
- MCP：只有 server/tool显式effect metadata或受控 adapter确认时记录具体 effect；否则 successful call附 `unknown` effect。
- task Tool：由 Phase 8 spawn relation支持 `child_task_spawn` observed。
- network read/external write必须区分；搜索/GET不能自动归为external_write。

## 5. 数据库增量

新增：

- `ansich_authorization_snapshots(snapshot_id, tool_call_id, policy_id, policy_version, policy_hash, decision, details_available, evaluated_obs_id, payload_id)`；每次 evaluation一个 snapshot。
- `ansich_authorization_permissions(snapshot_id, ordinal, resource, action, scope_id nullable, effect)`。
- `ansich_tool_call_authorizations(tool_call_id, snapshot_id, relation_obs_id)`。
- `ansich_tool_effects(effect_id, tool_call_id, effect_class, phase, scope_id nullable, target_hash, target_preview, fidelity_class, source_obs_id)`。
- `ansich_scope_conclusions(assertion_id, tool_call_id, conclusion_kind)`可作为 belief typed index，事实仍在 Belief tables。

索引 `(tool_call_id, evaluated_obs_id)`、`(decision, policy_id)`、`(effect_class, phase, scope_id)`、`(scope_id, tool_call_id)`。AuthorizationSnapshot和Effect都是 typed relation endpoint，不把它们塞入 ToolCall JSON。

## 6. Safety conclusions assessor

新增 `scope-safety@1`，只输出四类 conclusion：

- `policy_denial`：有 explicit denied evidence。
- `attempted_scope_violation`：intent目标越出有效 Scope，且被deny或未执行。
- `realized_scope_violation`：有 observed effect落在授权 Scope外。
- `unverified_effect`：Tool可能产生effect但当前只知道 unknown/无法验证。

判断必须引用 intent、AuthorizationSnapshot和Effect Observation。Tool最终文本不能单独支持 realized violation。相冲突 evidence都保留，resolver按 hard observed > structured authorization > declared potential选择当前 conclusion，但不能删除 unknown range。

对应 Alert episode沿用 Phase 6：attempted/realized Scope violation和unverified effect。对高风险 external_write/permission_change可以配置severity，但severity不是Task control state。

## 7. API 与 UI

新增：

```text
GET /api/ansich/tasks/{task_id}/scopes
GET /api/ansich/tool-calls/{tool_call_id}/authorization
GET /api/ansich/tool-calls/{tool_call_id}/effects
GET /api/ansich/operations/safety-events
```

Task detail增加 Scopes & Effects：顶部显示多 Scope及继承来源；下方按 Step/Tool显示 intent → authorization → effects。API对 path/target preview再次执行响应级敏感过滤，raw target只走 audited payload endpoint。

unknown effect必须在 UI中占据明确状态，不因没有effect rows而展示“No side effects”。只有 probe明确声明“观测范围内无 effect”且有 fidelity/evidence时才可显示受限的 none observed，并附coverage。

## 8. TDD 测试矩阵

- Scope：owner/thread/workspace/sandbox多值、parent scope、继承evidence、敏感path hash。
- Authorization：allow/deny/unknown、bool-only provider、policy version、middleware short-circuit、secret exclusion。
- Effects：file read/write/delete、process execute、network read、external write、task spawn、MCP/bash unknown。
- Conclusions：deny但未执行、intent越界、observed越界、success text无effect evidence、unknown effect。
- lineage：Tool intent/authorization/effect各自可追Observation，typed relation正反向索引。
- API/UI：多Scope、unknown coverage、target redaction、普通用户拒绝、safety filter。
- replay/late evidence：effect先于authorization、policy snapshot晚到、重复effect不重复Alert。
- fail-open/fail-safe：Ansich effect probe失败不改变原授权决定；DeerFlow deny仍阻止Tool。

## 9. 完成条件

- 每个受支持 ToolCall可独立查询 intent、AuthorizationSnapshot、raw execution和observed effects。
- Task支持多个 Scope并保留继承/归属角色。
- deny不被计作执行；exit code 0不被当作“无副作用”。
- bash/MCP无法验证的effect明确为unknown/unverified。
- attempted/realized violation都由结构化evidence支持，不能只根据Tool文字推断。

# Phase 7 — AgentRelease 与版本比较

## 1. 交付目标

本阶段为每个 Task 绑定不可变 AgentRelease。开发者可以看到该 Task 实际使用的模型配置、渲染基础 prompt、加载 Tool catalog、有效 runtime policy 和 DeerFlow build，并对两个 release 做结构化比较。

AgentRelease 代表 Task 开始时的有效 actor 配置。Task 执行期间的日期、memory 内容、summary、用户输入、激活 skill 正文和 Step 动态 promoted Tool schema 属于 ContextSnapshot，不进入 release hash。

## 2. Runtime descriptor，避免重复推导

不能从 `config.yaml` 单独“推测”release，因为 factory 可能 clamp 配置、过滤 Tool 或改变 middleware。重构 lead/subagent agent assembly，产出 `AgentRuntimeDescriptor`：

```text
namespace
agent_name
requested_model
effective_model
prompt_template_id/hash
rendered_base_prompt
soul_hash?
available_skill_catalog_hash
loaded_tools[]
middleware_chain[]
effective_policies{}
runtime_build{}
```

descriptor 必须在实际 model、prompt、tools、middleware 已装配后生成。保留现有 `make_lead_agent()` 返回 compiled graph 的兼容接口；内部 assembly 返回 `{graph, descriptor}`，由 Run context 接收 descriptor。不要另写一套 `describe_config()` 复制 factory 逻辑，否则两条路径会漂移。

Tool descriptor 保存 name、description、canonical argument JSON schema、source（builtin/MCP/community/skill）、deferred 状态和行为相关 metadata；不保存 callable repr、session object、OAuth token 或 server header。

middleware descriptor 保存有效顺序、稳定类型名和公开 policy 参数。只有会改变 Agent 行为的参数进入 policy；日志级别、队列长度、Ansich retention 等观测配置不进入 AgentRelease。

## 3. Policy hash 的具体组成

`policy_hash` 是有效运行策略 canonical manifest 的 SHA-256。v1 至少包含：

- middleware order；
- summarization 触发阈值、保留策略和 summary model identity；
- Tool output budget、truncation/externalization规则；
- token/step/wall-time/loop limits；
- guardrail/authorization policy ID 与 effective version；
- subagent enablement、类型 allowlist、max turns、timeout；
- plan/todo 和 non-interactive 行为；
- deferred Tool/search/skill activation策略；
- terminal response与安全 finish-reason handling。

requested 值只用于诊断；hash 输入使用 effective 值。例如 max tokens 被 provider/model clamp 后，以 clamp 后值 hash，同时 manifest 保存 requested/effective。动态 secret、runtime object address、当前时间和不稳定集合顺序必须排除。

## 4. Canonicalization 和 component hash

在独立 core 新增 `release/canonical.py` 与 `release/manifest.py`。canonical JSON 规则：UTF-8、object key 递归排序、紧凑 separators、显式 null策略、禁止 NaN/Infinity；语义为集合的 Tool catalog按 `(source,name,schema_hash)` 排序，middleware/消息等有序数组保持原序。

先计算：

```text
model_hash
prompt_hash
tool_catalog_hash
policy_hash
runtime_build_id
```

再对 `{namespace, agent_name, component_hashes}` canonical JSON 计算 `release_hash`。manifest schema version加入 hash，防止同字节在新语义下碰撞。所有 hash 使用 lowercase hex SHA-256。

runtime build优先记录 image digest/package version/git commit；不可得时为 explicit unknown。unknown是 manifest内容，会参与 hash，不能用当前工作目录或 object repr替代。

## 5. Secret sanitization

在 hash 和持久化前先 sanitize。字段 allowlist优先于 denylist；模型 config只允许 provider、model、endpoint class、行为参数，不允许 API key/base auth header。MCP Tool source保存 server logical name和transport kind，不保存完整 credential-bearing URL。

已知 secret exact-value filter作为第二层。若 sanitized manifest仍命中 credential field validator，release resolution失败并发 `observability.degraded`，Task继续执行但 `executed_by` Belief为 unknown；绝不为追求 release completeness存 secret。

写测试证明改变 API key/header/object memory address不改变 release hash，改变行为参数会改变。

## 6. 数据库与 Task 绑定

新增：

- `ansich_agent_releases(entity_id, namespace, agent_name, release_hash, schema_version, model_hash, prompt_hash, tool_catalog_hash, policy_hash, runtime_build_id, manifest_payload_id, discovered_obs_id, created_at)`；唯一 `(namespace, agent_name, release_hash)`。
- `ansich_agent_release_components(release_id, component_kind, component_hash, summary_json)`；唯一 `(release_id, component_kind)`。
- `ansich_task_agent_releases(task_id, release_id, relation_role, established_obs_id)`；v1 role=`executed_by`，每 Task一个 starting release。

manifest 以 payload 存储，read model 只保留安全 summary。Task admission 在 `task.created` 之后发 `agent_release.resolved`；这是 v0.2 Event kind catalog 尚未列出的协议扩展，因此编码前必须先把该 kind、payload schema 和版本补回设计文档。Structural projector 按 release hash dedupe 并建立 executed_by relation。

Task 中途 `external.config_changed` 不修改绑定；下一 Task重新 resolve。尝试对已有 release更新 manifest必须被 repository拒绝。

## 7. Provider-reported model 与 drift

每个 `llm.responded` 保存 provider-reported model/revision。它不是 release identity的一部分，因为 admission时未知。新增 assessor比较 attempt evidence与 release effective model：

- 能规范映射且一致：记录 matched measurement；
- 明确不一致：产生 `configuration_drift` rule Belief/Alert；
- provider不返回或 alias不可比较：unknown，不告警。

不能在第一个 response后修改 AgentRelease hash。一个 Task多个 attempt可报告不同 provider revision，全部作为 attempt evidence保留。

## 8. 比较 API

新增：

```text
GET /api/ansich/agent-releases
GET /api/ansich/agent-releases/{release_id}
GET /api/ansich/agent-releases/compare?left=...&right=...
```

compare 由后端生成 typed diff：

```text
model: requested/effective/parameters changed
prompt: template/rendered/soul/catalog hash changed
tools: added/removed/schema_changed/description_changed/source_changed
policy: changed paths with left/right values
build: package/image/git changed
```

不得要求前端对两份 raw JSON自行 diff。Tool schema diff按 stable Tool key匹配；同名不同 source不能误判为同一个 Tool。

列表支持 agent name、component hash、time filter，并返回 Task count、operational distributions的 availability。没有 evaluation时 quality字段返回 `unassessed`，不能说新 release“更好”。

## 9. 前端

Task detail增加 Agent Release 标签，显示 component hash、sanitized readable values和 provider drift evidence。新增 compare selector，允许从 Task当前 release选择另一个 release。

diff UI按 component分组；prompt默认只显示 hash/受控 preview，完整 payload走 raw audited endpoint；Tool schema用 structured tree。Operational metrics只显示事实分布，例如 token/Step/latency；质量卡在 Phase 10前显示“未评估”。

## 10. TDD 测试矩阵

- canonical JSON：key/set/order、Unicode、null、非法 float、schema version。
- fingerprint：完全相同 dedupe；model/prompt/Tool schema/policy/build任一变化产生新 hash。
- requested/effective：只 requested变化但 effective相同不改 behavior hash；诊断字段仍保留。
- sanitization：API key、header、DSN、MCP URL credential、runtime repr不落库/不影响 hash。
- assembly：descriptor与实际 compiled agent的 Tool/middleware/prompt一致，防止旁路构造。
- immutability：重复 resolve、冲突 manifest、Task中途 config change。
- provider drift：match/mismatch/unknown/多 attempt，不改 release。
- API/UI：typed diff、同名不同 source Tool、unassessed质量、raw payload lazy/audited。

## 11. 完成条件

- Task admission产生一个 sanitized immutable AgentRelease并建立 executed_by。
- 有效模型、rendered prompt、loaded Tool schema、policy或build变化都产生不同 release。
- secret和不稳定 runtime值既不泄漏也不制造假 release。
- provider-reported model只作为 attempt evidence，可触发 drift但不修改 release。
- compare API返回结构化 component diff；无 evaluation明确为 unassessed。

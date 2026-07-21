# Phase 9 代码评审跟进项

来源:commit `152f44c2`(Scope、授权与副作用审计)+ `089dfee0`(docs update)的代码评审(2026-07-21)。编号带 `H`(高)/`M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| H1 | AuthorizationSnapshot 不反映任何真实授权系统:`policy_id`/`policy_version` 硬编码常量,`decision` 只有 `allowed`/`denied` 两个值,`unknown` 在生产路径上永不产生 | ⬜ 未修复 | — | — |
| H2 | raw 结果终态为 `tool.failed`/`tool.timed_out`/`tool.cancelled` 时,observed effect 仍无条件以 `fidelity_class="hard"` 记录 | ⬜ 未修复 | — | — |
| M1 | `_effect_class` 分类法缺 `filesystem_delete`/`permission_change`(bash `rm`、chmod 等无法归类为专属 effect class) | ⬜ 未修复 | — | — |
| M2 | scope-safety assessor 每次触发都重扫任务全部 Scope 证据并重新评估每个 tool_call,而各 tool_call 结论本互相独立 | ⬜ 未修复 | — | — |
| L1 | 目标 path 敏感过滤只识别 POSIX 绝对路径(`startswith("/")`),Windows 路径可能绕过 intent 阶段与 API 响应端两层 redaction | ⬜ 未修复 | — | — |
| L2 | `/operations/safety-events` 把 `tool_call_id` 传给 `service.list_alerts(task_id=...)` 形参名具有误导性 | ⬜ 未修复 | — | — |

## H1. AuthorizationSnapshot 不反映任何真实授权系统

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/ansich/tool_middleware.py::_record_authorization`(tool_middleware.py:199-256)。`policy_id="deerflow-tool-middleware-chain"`、`policy_version="1"`、`details_available=False`、`effective_permissions=()` 在两个调用点(`_record_started` line 175-180 决策恒为 `"allowed"`;`AnsichVisibleToolMiddleware.wrap_tool_call` line 636-642 在 `not invocation.started` 时决策恒为 `"denied"`,`reason_code="short_circuited_before_callable"`)都是同一套硬编码常量,不读取任何真实授权来源。全仓库对 `deerflow.ansich` 下 import `GuardrailMiddleware`/`GuardrailRequest`/授权 adapter 的检索为空。
- 现状:计划 §3 明确要求 snapshot 应"在 Tool decision/execution 前,从 `deerflow.authz.adapter/provider`、sandbox policy、MCP/tool allowlist 和 run context 构造"。但当前实现只用"是否到达真实 callable 边界"这一个二值信号推断 `decision`——即使中间件链里 `GuardrailMiddleware`(backend/AGENTS.md 中间件链 #9,`guardrails.enabled` 时启用)对同一次调用产生了真实的 policy id、reason、effective permissions 并返回 deny,Ansich 记录的仍是与之无关的合成 `policy_id`。`decision="unknown"` 虽然在 schema(`contracts.py`/`safety.py`)与 `scope_safety.py` 判定逻辑中都被支持,但在生产代码路径里从未被构造过(`grep decision="unknown"` 只命中 `test_scope_safety_assessment.py` 里手工构造的领域测试)。
- 风险:运营者在 "Authorization" 面板或 `policy_denial`/`attempted_scope_violation` 告警里看到的 policy 身份是完全合成的、与实际生效的 RBAC/Guardrail 决策脱节;一旦后续接入真实 authz adapter(参考 `docs/plans/2026-07-10-pluggable-authorization-rfc.md`),现有 `policy_id`/`policy_hash` 历史数据将与新数据语义不可比。
- 方向:在 `_record_authorization` 调用点补齐从 `GuardrailMiddleware`(或其底层 `GuardrailProvider`/`GuardrailRequest`)读取真实 `policy_id`/`policy_version`/`decision`/`reason_codes` 的桥接;guardrails 未启用或 provider 只返回 bool 时按计划 §3 落 `details_available=false` 且不得补猜 `effective_permissions`。补充"guardrail 真实 deny 时 snapshot 携带其 policy 身份""guardrails 关闭时保持当前 fallback 语义不回归"的回归测试。
- 归属:应先于本阶段"生产就绪"门禁完成——在此之前,`policy_denial`/`realized_scope_violation` 等 D4 结论无法被信任为反映真实授权层。

## H2. raw 结果失败/超时/取消时,observed effect 仍以 `fidelity_class="hard"` 记录

- 状态:⬜ 未修复。
- 位置:`tool_middleware.py::_record_observed_effects`(tool_middleware.py:364-400)固定 `fidelity_class=("unknown" if effect_class == "unknown" else "hard")`,从不检查 `invocation.raw_terminal_kind`;调用方 `_record_raw_result`(tool_middleware.py:403-468)在 `accepted` 时无条件调用它,而 `raw_terminal_kind` 可以是 `tool.failed`/`tool.timed_out`/`tool.cancelled`(见 `AnsichRawToolMiddleware.wrap_tool_call`/`awrap_tool_call` 的异常分支,tool_middleware.py:723/765,均汇入 `_record_raw_result`)。
- 现状:`write_file` 因权限错误或沙箱超时而中途失败,`_effect_class("write_file")` 仍归类为 `filesystem_write`,于是记录一条 `fidelity_class="hard"` 的 `effect.observed{filesystem_write}`——即便写入可能根本没有完成。计划 §4/§6 明确 effect fidelity 是 `scope-safety@1` 判定 `realized_scope_violation`(critical 级告警)的直接依据,过度确信的 `hard` fidelity 会在失败调用上产生假阳性"已越权"结论。当前唯一覆盖该函数的测试(`test_execution_context.py` 里两个 `timeout_tool` 用例)用的 `tool_name="timeout_tool"`,而 `_effect_class` 把它归类为 `"unknown"`——即分支必然落到 `fidelity_class="unknown"`,永远测不到具名工具(`write_file`/`bash` 等)在失败终态下被错误标记为 `"hard"` 的路径。
- 方向:在 `_record_observed_effects` 增加 `invocation.raw_terminal_kind == "tool.returned_raw"` 的门控,非正常返回时 fidelity 降级(如 `"unverified"` 或既有的 `"unknown"`)。补一条"具名工具在 failed/timed_out/cancelled 终态下不产出 hard fidelity effect"的回归测试,覆盖 `write_file`/`bash` 而非仅 `timeout_tool`。
- 归属:应尽快修复,理由与 H1 相同——直接影响 D4 Safety Audit 判定结论的可信度。

## M1. Effect class 分类法缺 `filesystem_delete`/`permission_change`

- 状态:⬜ 未修复。
- 位置:`tool_middleware.py::_effect_class`(tool_middleware.py:259-271)。当前分支只能返回 `filesystem_read`/`filesystem_write`/`process_execute`/`child_task_spawn`/`network_read`/`unknown`;`bash rm -rf`、直接文件删除工具、以及任何权限变更操作都落入笼统的 `process_execute` + `unknown`,不会产生计划 §4 明确列出的 `filesystem_delete` 或 `permission_change`。
- 现状:需要说明的是,Phase 9 的"实现状态"说明已明确把 **MCP 显式 effect metadata** 与 **外部写 adapter 的更细 resource canonicalization** 延后到 Phase 11 加固边界——因此 `external_write`(MCP/外部系统写入)缺失属于已知且已登记的范围,不在本条重复跟进。本条只覆盖该说明未提及的两类:纯本地文件删除(`filesystem_delete`)与权限变更(`permission_change`),它们与"外部写 adapter"无关,理论上可以在当前 DeerFlow 内置 file 工具/bash 层直接识别,但目前完全没有生产路径产生,也没有任何测试覆盖(`grep filesystem_delete/permission_change` 除本文档外全仓库零命中)。
- 方向:为内置文件删除工具(如有)与识别 `rm`/`unlink`/`chmod`/`chown` 等 bash 子命令模式补充分类;对于无法可靠静态识别的 bash 内部效果,继续按 `unknown` 处理(不越权断言),但至少为已知的内置工具路径补齐两个 class。补充对应 TDD 用例(计划 §8 "Effects" 矩阵要求的 file delete/process execute 分支)。
- 归属:不阻塞 Phase 9 合并;建议随 Phase 11 的 effect 分类加固一并处理,或作为独立小改动提前完成。

## M2. scope-safety assessor 每次触发都重扫任务全部证据并重估所有 tool_call

- 状态:⬜ 未修复。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_assess_scope_safety_at`(sql.py:1430-1475)查询任务全部 `_SAFETY_PROJECTION_KINDS` observation(不按 tool_call 过滤),并对结果中出现的**每一个** `tool_call_id`重新调用 `assess_scope_safety`。
- 现状:assessor job 的 claim/coalesce 逻辑(`_claim_assessor_job`,sql.py:1171-1225)按 `(subject_id, assessor_name, assessor_version)` 分组吸收同批次可认领 job,这是 Phase 6 M1(`4f5ec989`)已经落地的通用基础设施,scope-safety 复用它并不构成对该项的回归。但与 `assess_action_repetition`/`assess_tool_frequency` 不同——那两者的判定语义本就需要整段 Step/Tool 序列(重复检测必须看到全部历史)——`scope-safety` 的每个 conclusion 在领域上是**按 tool_call 独立**的(`assess_scope_safety` 只吃单个 `tool_call_id` 的 snapshot/effect 集合)。因此每次评估都重新计算任务里所有历史 tool_call 的结论,是比其他 assessor 更明确可避免的浪费:一个有 N 个 tool_call 的长任务,晚期每条新 authorization/effect observation 都会触发一次对全部 N 个 tool_call 的重新判定与 `_persist_assessment`/`_reconcile_alerts_for_assessment` 写入,序列化到达场景下总代价趋向 O(N²)。
- 方向:`_assess_scope_safety_at` 增加"只重估本次 watermark 区间内新出现证据所涉及的 `tool_call_id` 集合"的过滤(例如从新增 observation 反查涉及的 tool_call_id,而不是重新扫描并重估全部);已收敛(无新证据)的历史 tool_call 结论应保持不变、不重复写入。配"贡献/证据增长时重估工作量不随任务历史线性增长"的性能护栏测试,方法上可参考 phase-8-review-followups.md M2 的建议写法。
- 归属:不阻塞 Phase 9 合并(v1 admin-only、单任务规模有限);建议归入 Phase 11(生产韧性/多 worker)前的批量治理,可与 phase-8 M1/M2 的 wall_time 通道治理一并规划。

## L1. 目标 path 敏感过滤只识别 POSIX 绝对路径

- 状态:⬜ 未修复。
- 位置:`tool_middleware.py::_effect_target_preview`(tool_middleware.py:274-285)与 `backend/app/gateway/routers/ansich.py::_safe_effect_payload`(ansich.py:1238-1247)都用 `preview.startswith("/")` 判断是否需要把预览折叠成 `<absolute>/<basename>`。
- 现状:`_effect_target_preview` 会先 `value.replace("\\", "/")` 再 `posixpath.normpath`,一个 Windows 路径如 `C:\Users\alice\secret.txt` 规整后变成 `C:/Users/alice/secret.txt`——不以 `/` 开头,因此**不会**被折叠,原样作为 `target_preview` 持久化;`_safe_effect_payload` 在 API 响应端做的二次兜底过滤同样只认 `/` 前缀,同一条路径原样透出到 "Scopes & effects" UI。`backend/AGENTS.md` 明确 `LocalSandboxProvider` 支持 Windows 本地沙箱部署,因此这不是纯理论场景。
- 方向:redaction 判断改为同时识别 POSIX 绝对路径与 Windows 绝对路径(如 `^[A-Za-z]:/` 或 UNC `^//`),两处保持一致。补充 Windows 风格路径不泄漏的回归测试(intent 阶段 + API 响应层各一条)。
- 归属:非阻塞;建议随下一次触达这两个函数的改动顺带处理。

## L2. `/operations/safety-events` 传参名具有误导性

- 状态:⬜ 未修复。
- 位置:`backend/app/gateway/routers/ansich.py::list_safety_events`(ansich.py:1280-1319)把查询参数 `tool_call_id` 传给 `service.list_alerts(task_id=tool_call_id, ...)`。
- 现状:当前行为正确——`AnsichScopeConclusionRow`/scope-safety `Assessment.subject_id` 本就是 `tool_call_id`(sql.py:1396),`list_alerts` 的 `task_id` 形参在存储层过滤的是 `AnsichAlertRow.subject_id`,两者语义吻合,不是 bug。但形参名 `task_id` 会让后续维护者误以为在按 Task 过滤,存在被误用/误改的风险。
- 方向:服务层 `list_alerts` 的形参改名为更中性的 `subject_id`(或在该路由调用处加注释说明"scope-safety 告警的 subject 就是 tool_call_id"),不需要变更行为。
- 归属:非阻塞,顺手清理项。

## 评审中确认无需跟进的点(留档)

- **敏感字段三层拦截**:`AuthorizationSnapshot._bool_only_provider_has_no_permissions`、`ToolEffect._exclude_credentials`(`backend/packages/ansich/ansich/safety.py`)与 `ObservationEnvelope._validate_subject` 的全 payload `_find_secret_field` 扫描(`contracts.py`)三层独立拦截 JWT/cookie/API key/Authorization header 类内容,经直接代码走查确认。
- **`details_available=false ⇒ effective_permissions` 必须为空**由 `safety.py` 的 Pydantic validator 结构性保证,符合计划 §3;即便 H1 指出 `details_available` 目前恒为 `False`,该约束本身是稳固的,后续接入真实 provider 时可直接复用。
- **fail-open 边界**:`tool_middleware.py` 中所有 Ansich 记录调用均包在 `try/except: pass` 或返回 `False` 内;`AnsichRawToolMiddleware` 无论探针是否失败都会调用真实 `handler(request)` 并重新抛出原始异常(`except GraphBubbleUp: raise` + 兜底 `raise`),确认不改变 DeerFlow 真实执行结果。
- **`child_task_spawn` 不在 `_record_observed_effects` 产生**(tool_middleware.py:372-373 提前 return)——由 Phase 8 的 `TaskControlProbe.created()` 作为权威信号,正确避免了与 phase-8-review-followups.md M1(`wall_time_ms` 双写者)同类的双写陷阱。
- **`scope_safety.py::assess_scope_safety`** 在授权决策非 `allowed` 时正确拒绝产生 `attempted_scope_violation`/`realized_scope_violation`(`allowed_scope_ids` 保持为空,`outside_intents`/`outside_observed` 因此为空)——"unknown ≠ violation" 的要求被正确落实(该分支目前因 H1 而从未被生产数据触达,但领域逻辑本身是对的)。
- **迁移 `0020_ansich_scope_safety.py`**:upgrade/downgrade 对称,FK `CASCADE`/`RESTRICT` 语义合理,计划 §5 列出的四个索引(`(tool_call_id, evaluated_obs_id)`、`(decision, policy_id)`、`(effect_class, phase, scope_id)`、`(scope_id, tool_call_id)`)均已精确落地。
- **SQL 投影 `_project_authorization_snapshot`/`_project_tool_effect`**:幂等、对冲突重投影会 raise、通过 `_ProjectionDependencyPending` 正确等待被引用的 ToolCall/Scope 行——投影路径本身没有 M2 描述的重复计算问题(问题只在 assessor 读路径)。

## 计划测试矩阵缺口(随修复补齐)

- H1:`decision="unknown"` 在生产代码路径(而非手工构造的领域测试)零覆盖;`tool_middleware.py` 新增记录函数没有独立于 `AnsichExecutionContext`/`AnsichService` 集成路径之外的单元测试文件。
- H2:失败/超时/取消终态下具名工具(`write_file`/`bash` 等,而非 `_effect_class` 恒返回 `unknown` 的 `timeout_tool`)的 observed effect fidelity 零覆盖。
- M1:`filesystem_delete`、`permission_change` 两个 effect class 零生产路径、零测试覆盖。
- M2:贡献/证据数增长时 scope-safety 重估工作量不随任务历史线性增长——尚无性能护栏测试(参考 phase-6-review-followups.md M1 的 SQL 监听回归写法)。
- API/UI:`test_ansich_router.py` 本次仅新增 26 行覆盖 4 个新端点,不足以独立确认 `_safe_effect_payload` 的敏感模式/绝对路径两个分支都被真实触达;建议补充针对性用例,尤其是 L1 的 Windows 路径分支。

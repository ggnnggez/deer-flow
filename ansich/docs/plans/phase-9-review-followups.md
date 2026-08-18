# Phase 9 代码评审跟进项

来源:commit `152f44c2`(Scope、授权与副作用审计)+ `089dfee0`(docs update)的代码评审(2026-07-21)。编号带 `H`(高)/`M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| H1 | AuthorizationSnapshot 不反映任何真实授权系统:`policy_id`/`policy_version` 硬编码常量,`decision` 只有 `allowed`/`denied` 两个值,`unknown` 在生产路径上永不产生 | ✅ 已修复 | 2026-07-21 | `fa1e0ae7`/`90db5180`/`52594604` |
| H2 | raw 结果终态为 `tool.failed`/`tool.timed_out`/`tool.cancelled` 时,observed effect 仍无条件以 `fidelity_class="hard"` 记录 | ✅ 已修复 | 2026-07-23 | 本次变更(待提交) |
| M1 | `_effect_class` 分类法缺 `filesystem_delete`/`permission_change`(bash `rm`、chmod 等无法归类为专属 effect class) | ⬜ 未修复 | — | — |
| M2 | scope-safety assessor 每次触发都重扫任务全部 Scope 证据并重新评估每个 tool_call,而各 tool_call 结论本互相独立 | ⬜ 未修复 | — | — |
| L1 | 目标 path 敏感过滤只识别 POSIX 绝对路径(`startswith("/")`),Windows 路径可能绕过 intent 阶段与 API 响应端两层 redaction | ⬜ 未修复 | — | — |
| L2 | `/operations/safety-events` 把 `tool_call_id` 传给 `service.list_alerts(task_id=...)` 形参名具有误导性 | ⬜ 未修复 | — | — |
| H3 | `AnsichEntityRow` 与其类型化子行(AuthorizationSnapshot/AgentRelease/Alert)之间无 ORM `relationship()`,同一次 flush 插入顺序不保证,FK 强制开启的生产环境下确定性失败 | ✅ 已修复 | 2026-07-22 | `e074bd60` |
| H4 | `DELETE FROM ansich_belief_assertions` 在 `PRAGMA foreign_keys=ON` 下违反 FK 约束 | ✅ 已修复 | 2026-07-23 | `b9c1f9e8` |
| H5 | 大 payload externalize 后的 ContextSnapshot 在 FK 强制开启时静默失败,`get_step_context` 返回 None | ✅ 已修复 | 2026-07-23 | `b9c1f9e8` |
| H6 | `_persist_assessment` 插入 `AnsichBeliefAssertionRow` 前不检查 `subject_id` 对应的 Entity 是否已存在,scope-safety(`subject_id`=tool_call_id)在其 ToolCall 尚未投影时硬失败 5 次耗尽重试,而非像 projector 一样优雅走 `_ProjectionDependencyPending` | ✅ 已修复 | 2026-08-18 | 本次变更(待提交) |
| H7 | Collector 有界队列 fail-open 丢弃后,若进程在后续成功持久化/周期评估前重启,内存 loss 状态尚无可确认的持久证据 | ✅ 已修复 | 2026-08-18 | 本次变更(待提交) |

## H1. AuthorizationSnapshot 不反映任何真实授权系统

- 状态:✅ 已修复(2026-07-21,`fa1e0ae7`/`90db5180`/`52594604`)。新增中立契约 `deerflow.authz.outcome`(`AuthorizationOutcome` + `__`前缀 context key `__authorization_outcome`):`GuardrailMiddleware` 在 allow/deny/provider-error 各分支于 `handler`/denied 之前把真实决策(`policy_id`/`policy_version`/`decision`/`reason_codes`)写入 `runtime.context`,Ansich 两个探针(raw 的 `_record_started`、visible 的 `not started` 短路)pop-on-read 消费并据此构造 snapshot。**无真实授权层时(guardrails 关闭或未对该 tool 求值)记 `decision="unknown"`**——首次让 `unknown` 走进生产路径,并消除「ReadBeforeWrite/ToolProgress 等非授权短路被冒充成 `policy_denial`」的假阳性。`details_available` 仍恒 `false`、`effective_permissions` 仍为空(`GuardrailDecision` 不暴露结构化权限,符合计划 §3;结构化权限留给接入真实 authz adapter 时扩展)。回归覆盖:`tests/test_authorization_outcome.py`、`tests/test_guardrail_middleware.py::TestGuardrailWritesAuthorizationOutcome`、`tests/ansich/test_execution_context.py`(真实 allowed/denied、无授权 unknown、放行但被下游拦截仍记 allowed)、`tests/ansich/test_scope_safety_assessment.py`(unknown/allowed 不产 `policy_denial`)。
- 原始诊断(留档):
- 位置:`backend/packages/harness/deerflow/ansich/tool_middleware.py::_record_authorization`(tool_middleware.py:199-256)。`policy_id="deerflow-tool-middleware-chain"`、`policy_version="1"`、`details_available=False`、`effective_permissions=()` 在两个调用点(`_record_started` line 175-180 决策恒为 `"allowed"`;`AnsichVisibleToolMiddleware.wrap_tool_call` line 636-642 在 `not invocation.started` 时决策恒为 `"denied"`,`reason_code="short_circuited_before_callable"`)都是同一套硬编码常量,不读取任何真实授权来源。全仓库对 `deerflow.ansich` 下 import `GuardrailMiddleware`/`GuardrailRequest`/授权 adapter 的检索为空。
- 现状:计划 §3 明确要求 snapshot 应"在 Tool decision/execution 前,从 `deerflow.authz.adapter/provider`、sandbox policy、MCP/tool allowlist 和 run context 构造"。但当前实现只用"是否到达真实 callable 边界"这一个二值信号推断 `decision`——即使中间件链里 `GuardrailMiddleware`(backend/AGENTS.md 中间件链 #9,`guardrails.enabled` 时启用)对同一次调用产生了真实的 policy id、reason、effective permissions 并返回 deny,Ansich 记录的仍是与之无关的合成 `policy_id`。`decision="unknown"` 虽然在 schema(`contracts.py`/`safety.py`)与 `scope_safety.py` 判定逻辑中都被支持,但在生产代码路径里从未被构造过(`grep decision="unknown"` 只命中 `test_scope_safety_assessment.py` 里手工构造的领域测试)。
- 风险:运营者在 "Authorization" 面板或 `policy_denial`/`attempted_scope_violation` 告警里看到的 policy 身份是完全合成的、与实际生效的 RBAC/Guardrail 决策脱节;一旦后续接入真实 authz adapter(参考 `docs/plans/2026-07-10-pluggable-authorization-rfc.md`),现有 `policy_id`/`policy_hash` 历史数据将与新数据语义不可比。
- 方向:在 `_record_authorization` 调用点补齐从 `GuardrailMiddleware`(或其底层 `GuardrailProvider`/`GuardrailRequest`)读取真实 `policy_id`/`policy_version`/`decision`/`reason_codes` 的桥接;guardrails 未启用或 provider 只返回 bool 时按计划 §3 落 `details_available=false` 且不得补猜 `effective_permissions`。补充"guardrail 真实 deny 时 snapshot 携带其 policy 身份""guardrails 关闭时保持当前 fallback 语义不回归"的回归测试。
- 归属:应先于本阶段"生产就绪"门禁完成——在此之前,`policy_denial`/`realized_scope_violation` 等 D4 结论无法被信任为反映真实授权层。

## H2. raw 结果失败/超时/取消时,observed effect 仍以 `fidelity_class="hard"` 记录

- 状态:✅ 已修复(2026-07-23,本次变更待提交)。按 TDD 先新增生产中间件路径回归,覆盖 `write_file`/`bash` × `tool.failed`/`tool.timed_out`/`tool.cancelled` 六种组合,确认修复前每种组合的 `effect.observed` 都至少包含一条 `fidelity_class="hard"`。`_record_observed_effects` 现在只在 `invocation.raw_terminal_kind == "tool.returned_raw"` 且 effect class 已知时记录 `hard`;失败、超时、取消以及未知 effect class 一律降级为既有的 `unknown`,保留 observed 证据但不再把"调用结束"误断言为"副作用已完成"。最终全量 `backend/tests/ansich/` 为 330 passed。
- 原始诊断(留档):
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

## H3. Entity + 类型化子行的 flush 顺序不保证,FK 强制开启时确定性失败

- 状态:✅ 已修复(2026-07-22,`e074bd60`)。来源:排查用户真实开发库(`backend/.deer-flow/data/deerflow.db`)里 69 条永久失败(`attempts=5`,重试 4 轮均复现同一错误)的 job 时发现,不是 U3 failed-job 诊断功能本身的 bug,而是 Phase 9 上线后新数据路径首次踩中的既有投影 bug。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py` 六处"先 `session.add(AnsichEntityRow(...))`、再 `session.add(<类型化子行>)`、最后统一 `await session.flush()`"的写法——`_project_control`(entity+task)、`_project_agent_release`(payload+release,entity 部分已有 flush 但 `manifest_payload_id` 依赖漏了)、`_project_scope_snapshot`(entity+scope)、`_project_authorization_snapshot`(entity+snapshot)、`_project_tool_effect`(entity+effect)、`_persist_alert_episode`(entity+alert,以及 alert 行+evidence 行两处依赖)。
- 现状:`AnsichEntityRow` 与这些类型化子行之间**只有裸 `ForeignKey`,没有 SQLAlchemy `relationship()`**。`backend/AGENTS.md` 明确"SQLite 生产连接强制外键"(`PRAGMA foreign_keys=ON`),但同一次 `flush()` 里 SQLAlchemy 对无 `relationship()` 关联的两个新对象**不保证**插入顺序——子表名字母序排在 `ansich_entities` 之前时(`ansich_authorization_snapshots`、`ansich_agent_releases`、`ansich_alerts`)会先尝试插子行,同一事务内 FK 校验失败并整体回滚,且不可通过重试自愈(每次都复现同一顺序)。真实库命中:`task-safety` projector(`ansich_authorization_snapshots`)66 次、`task-structural` projector(`ansich_agent_releases`)2 次、scope-safety assessor(`_persist_alert_episode` 的 `ansich_alert_evidence`)1 次。**测试套件长期没测出来的原因**:`test_sql_safety.py`/`test_sql_agent_releases.py`/`test_sql_alerts.py` 里覆盖这几条路径的测试此前都没有开 `PRAGMA foreign_keys=ON`,FK 约束在 SQLite 里是逐连接开关,不开就不校验。
- 方向(已落地):在每处依赖的 `session.add()` 后立即插入一次 `await session.flush()`,把隐式排序依赖换成显式顺序,不依赖 ORM `relationship()`。回归覆盖:给上述三个测试文件里各自最贴近的一个已有测试打开 FK 强制,通过 `git stash` 确认改动前 RED、改动后 GREEN,再跑全量 `tests/ansich/`(323 passed,仅剩下方 H4/H5 之外的、无关的 `test_sql_budget.py` 预存 flaky)确认无回归。
- 归属:已完成。

## H4. `DELETE FROM ansich_belief_assertions` 在 FK 强制开启时违反约束

- 状态:✅ 已修复(2026-07-23,`b9c1f9e8`)。给两条相关测试启用 `PRAGMA foreign_keys=ON` 后稳定复现;逐一核对全部 assertion 引用方与命中数据,确认 `ansich_current_beliefs`、`ansich_belief_evidence`、`ansich_scope_conclusions` 已是 `ON DELETE CASCADE`,实际阻断删除的是 `ansich_task_summaries.assertion_id` 的默认 `NO ACTION`。该列是可重建读模型指针,现有 `list_tasks` 契约又明确要求 assertion 缺失时保留 Task、返回 degraded,因此修复为 nullable + `ON DELETE SET NULL`,而不是级联删除 TaskSummary。新增 `0021_ansich_summary_assertion_fk` 可逆迁移(降级前丢弃已无法恢复 assertion 指针的 NULL summary,随后恢复旧约束),并让 Phase 9 迁移升降级测试全程在 FK 强制下使用合法父行。回归覆盖 create-all schema 的缺失 assertion 退化读取与 Alembic upgrade/downgrade schema;最终全量 `backend/tests/ansich/` 为 324 passed。
- 原始诊断(留档):
- 位置:命中的两个测试——`test_sql_safety.py::test_phase9_safety_migration_upgrades_sqlite`(alembic 升降级测试)、`test_sql_task_lifecycle.py::test_list_tasks_uses_one_joined_query_and_keeps_page_length_with_a_missing_assertion`(模拟"缺失 assertion"退化场景)——报错均为同一条语句:`sqlite3.IntegrityError: FOREIGN KEY constraint failed [SQL: DELETE FROM ansich_belief_assertions WHERE ansich_belief_assertions.assertion_id = ?]`。两处触发路径不同但报错语句完全一致,提示是某个共享的清理/重建/降级代码路径删除 `ansich_belief_assertions` 行时,没有先删除或未正确级联仍引用该 assertion 的子行(`AnsichBeliefEvidenceRow`、`AnsichScopeConclusionRow`、`AnsichCurrentBeliefRow` 等均有 `assertion_id`/`source_assertion_id` 外键,需要逐一核实各自的 `ondelete` 设置与实际删除顺序)。
- 现状:与 H3 是**不同性质**的 bug——H3 是"同一 flush 内两个新增 INSERT 顺序不保证",这里是 DELETE 顺序/级联配置问题,需要独立走 Phase 1 根因排查(读错误、复现、查最近改动、对比 CASCADE/RESTRICT 配置)才能定位到具体是哪个函数、哪张子表。
- 方向:先用本次证明有效的技术复现(给相关测试引擎打开 `PRAGMA foreign_keys=ON` 并单独跑),定位到具体调用 `DELETE FROM ansich_belief_assertions` 的函数,核对该表被引用方的 `ForeignKey(..., ondelete=...)` 设置是否需要改成 `CASCADE`,或者删除代码本身需要先删子行。
- 归属:未定,建议下一个 Ansich 迭代窗口专门排查;由于是 DELETE 路径(而非 H3 的 INSERT 路径),不确定是否影响当前默认关闭 FK 校验的部署,但 `backend/AGENTS.md` 明确生产 SQLite 连接强制外键,不能默认认为无影响。

## H5. 大 payload externalize 后的 ContextSnapshot 在 FK 强制开启时静默投影失败

- 状态:✅ 已修复(2026-07-23,`b9c1f9e8`)。给目标测试启用 `PRAGMA foreign_keys=ON` 后先读 `ansich_projection_errors`,结果为空;同时数据库只有 `task.created`/`step.started`,证明失败尚未进入 projector,推翻了下方"投影异常被吞"的原假设。临时截获持久化边界取得真实异常:`sqlite3.IntegrityError: FOREIGN KEY constraint failed [SQL: INSERT INTO ansich_observations ... payload_ref_id ...]`,命中 externalized `llm.requested`。根因是 `persist_and_project` 同一事务内 add `AnsichPayloadRow` 后未显式 flush,随即插入引用它的 `AnsichObservationRow`;FK-on 下父行尚不可见,异常又被 `AnsichService._persist_items` 按 fail-open 语义折叠成 `storage_failure`/observation loss,所以表面才是 Step/ContextSnapshot 消失。修复是在 externalized observation payload 写入后显式 `await session.flush()` 再插 observation;目标用例现在同时锁定 FK-on、payload externalize、ContextSnapshot 可查询与原文懒加载;最终全量 `backend/tests/ansich/` 为 324 passed。
- 原始诊断(留档):
- 位置:`test_sql_task_lifecycle.py::test_large_content_payload_is_externalized_but_remains_lazy_queryable`(`inline_payload_max_bytes=128` 触发 payload externalize 路径)。失败现象是 `service.get_step_context(step.step_id)` 返回 `None`,而不是像 H3/H4 那样抛出可见的 `IntegrityError`——说明底层投影失败被某个 `try/except` 吞掉、只在 `ansich_projection_errors`/`_failed_jobs` 计数里留痕,断言层面表现为"数据消失"而非报错,排查时需要先用 U3 新增的 `list_failed_jobs`/`get_failed_job_detail`(或直接查 `ansich_projection_errors`)取出真实异常文本,而不是靠测试断言反推。
- 现状:未确认是否与 H3/H4 同属"缺 flush 顺序保证"这一类,还是 Phase 2/4 的 ContextSnapshot/ContentBlob externalize 投影路径里的另一个独立问题——两者都可能,需要先复现取得真实报错文本才能判断。
- 方向:复用 H3 定位时用过的技术(monkeypatch `_record_projection_error`/`_record_assessor_error` 打印完整 traceback,或直接读 `ansich_projection_errors.message`)取得真实异常;若确认也是 entity+子行插入顺序问题,按 H3 的模式补 flush;若是别的原因,按 Phase 1 流程另行分析。
- 归属:未定,建议与 H4 一起排查——两者都是同一次全局 FK 扫描发现,可以合并成一次调查窗口。

## H6. `_persist_assessment` 缺少 subject Entity 存在性检查,scope-safety 硬失败而非优雅等待

- 状态:✅ 已修复(2026-08-18,本次变更待提交)。按 TDD 新增 FK-on SQL 回归,构造 scope-safety 已看到 AuthorizationSnapshot、但其 subject ToolCall 尚未投影的真实依赖乱序:修复前 assessor 直接撞 FK 并消耗 attempt/写 error;现在 `_persist_assessment` 先查 subject Entity,缺失时抛 `_ProjectionDependencyPending`,且 assessor error 路径将其保留为 `pending`、回退 attempt、不写硬错误。随后 `step.started`/`tool.issued` 落地 Entity 后同一 assessor 自愈完成并产出 Belief。同日复核补齐等待上界:assessor job 增加持久化 `dependency_pending_since` 锚点(迁移 `0022_ansich_assessor_deadline`),复用 `projector_dependency_timeout_seconds` 截止——subject 永不出现时(正是 H7 描述的永久丢弃场景)越过截止即转 durable `failed`、写 assessor error 行并计入 failed-job 诊断面,`retry_failed_projections` 重置锚点后仍可自愈,而不是以 250ms 节奏无限重试且永不进入运维视野;完成与非依赖错误路径同步重置锚点,与 projector 的依赖等待语义完全对齐。回归:`test_scope_safety_dependency_wait_crosses_deadline_into_failed_job_and_retry`(超时转 failed + 错误行 + retry 自愈)与既有自愈用例共同锁定两种终局。
- 位置:`backend/packages/harness/deerflow/ansich/persistence/sql.py::_persist_assessment`(约 sql.py:1931 起)。该函数被全部 assessor(`action-repetition`/`tool-frequency`/`absolute-limits`/`configuration-drift`/`scope-safety`)共用,构造并 `session.add()` 一个新 `AnsichBeliefAssertionRow(subject_id=assessment.subject_id, ...)` 前,**不像各 projector 那样先 `session.get(AnsichEntityRow, subject_id)` 做依赖检查、缺失时 `raise _ProjectionDependencyPending`**,而是直接插入。`AnsichBeliefAssertionRow.subject_id` 有 `ForeignKey("ansich_entities.entity_id", ondelete="CASCADE")`(models.py:1033)。
- 现状:对 task 级 assessor(action-repetition 等),`subject_id` 就是 task_id,Task 的 Entity 行在 `task.created` 时极早创建,这个洞长期不暴露。但 scope-safety assessor 的 `subject_id` 是 **tool_call_id**(sql.py `_run_assessor` 里 `AnsichScopeConclusionRow(tool_call_id=assessment.subject_id, ...)` 印证),ToolCall 的 Entity 行要等它自己的 `tool.issued` 投影完成才存在。一旦这个 ToolCall 因为别的原因(例如 H7)迟迟没被投影,scope-safety assessor 仍会按 watermark 正常被触发,`INSERT INTO ansich_belief_assertions` 直接撞上 FK 约束,**5 次重试全部同样失败、耗尽 attempts 上限、不可能通过重试自愈**——跟真正的"证据还没到"这种应该走 `_ProjectionDependencyPending` 优雅等待的场景,在结果上被错误地当成了硬失败。真实复现:上述 Task 的 scope-safety assessor 5 条失败 job,报错均为 `INSERT INTO ansich_belief_assertions ... FOREIGN KEY constraint failed`。
- 方向(已落地):在 `_persist_assessment` 开头补 `if await session.get(AnsichEntityRow, assessment.subject_id) is None: raise _ProjectionDependencyPending(...)`,并补齐 assessor job 对该异常的无 attempt 等待分支,与 projector 的依赖等待语义保持一致;因为该函数是全 assessor 共用的,这个检查对 task 级 assessor 是无成本的(Entity 早就存在,`session.get` 立刻命中)。回归锁定"scope-safety 在其 ToolCall 尚未投影时优雅等待而非硬失败,依赖到位后能自愈"。
- 归属:未定;建议与 H7 一起排查——H6 是 H7 级联失败链条的下游表现之一(如果 H7 修复后 ToolCall 投影不再卡住,H6 描述的场景会更少触发,但 H6 本身作为"assessor 缺依赖检查"的通用防御仍然值得独立修,不应只依赖上游不再出问题)。

## H7. Step 的 `step.started` 观测缺失,导致该 Step 全部后续 projection 级联永久失败

- 状态:✅ 已修复(2026-08-18,本次变更待提交)。复核现有代码后校正了“loss 从不落盘”的原判断:后续任一批 Observation 成功持久化时,`_report_degradation_if_storage_recovered` 会把未报告的 task-scoped range 写成 durable `observability.degraded` Observation;周期 `assess_operations` 也会把当时的内存 range 写入运行中 Task 的 `ansich_active_task_read_model.lost_ranges_json`。真实缺口是**丢弃后尚未发生这两条后续路径就重启**,以及 active read model 的 range 会被重启后的空内存刷新覆盖。修复在 core service 的 `queue_full`/`queue_bytes_full` 丢弃当下发结构化 stdlib WARNING,包含 UTC 检测时间、reason、task/producer/sequence range 与队列水位;每实例 60 秒至多一条并记录 suppressed 数,日志失败自身继续 fail-open。无需迁移,UI 集成仍按方向③延期。
- 现象:Task `2832a0c9-713f-49c9-85b2-c79b3e621058` 里 step `d57df823-fe04-49ed-b727-4fd00a15949d` 的观测序列(按 `ingest_seq` 排序)第一条直接是 `llm.requested`(ingest_seq 2878),**完全没有 `kind='step.started'` 的观测**——不是投影失败,是这条观测在 `ansich_observations` 表里根本不存在。该 step 的 `llm.requested` 载荷 `actor_kind="subagent"`,确认是真实 Step(非 system operation,后者本就不产生 `step.started`,见下方排除项)。`task-step` projector 处理该 step 的 `llm.requested` 时因此报 `_ProjectionDependencyPending: step.started has not been projected: d57df823-...`,等了 4 小时以上(远超 `projector_dependency_timeout_seconds` 默认 300s)后不可逆地进入 `failed`(`attempts=0`,证明它一直在正常等待、不是执行报错)。级联:这条 job 卡住 → 同一 step 后续的 `llm.responded`/`tool.issued`/`tool.started`/`tool.returned_raw`/`effect.*`/`authorization.*` 全部因排在它之后而连带 `failed` → `tool.issued` 卡住导致该 ToolCall 的 Entity 行从未创建 → scope-safety assessor 撞上 H6。
- 排查过程与结论:
  1. **已排除:探针未被调用**。`AnsichDecisionMiddleware.wrap_model_call`/`awrap_model_call`(`middleware.py:50-100`)对每次真实 Agent 决策都无条件调用 `_record_step_started`;`_record_step_started`(`middleware.py:342-359`)只在 `call.step_id is None or call.step_seq is None` 时提前 return——而这只发生在 `actor_kind="system_operation"`(`execution.py::begin_call` 显式把 system operation 的 `step_id`/`step_seq` 设为 `None`,这是设计如此,给内部 title/summarization/memory 调用用的)。本例 `actor_kind="subagent"` 时 `begin_call` 必然分配真实 `step_id=new_id()`/`step_seq=<int>`,不会走提前 return 分支——探针代码本身逻辑正确,没有跳过这个 Step。
  2. **高置信度根因:Collector 有界队列 fail-open 丢弃**。`_record_step_started` 通过 `_record()`(`middleware.py:904-909`)调用 `execution.service.record(observation)`,`_record()` 把返回值直接丢弃、任何异常都吞掉返回。`AnsichService.record_batch`(`packages/ansich/ansich/service.py:146-183`)在 `queue_full`(`len(self._queue) + len(batch) > self._capacity`)、`queue_bytes_full`(队列字节水位超限)等条件下会调用 `_record_batch_loss` 记账后返回 `accepted=False`,**不抛异常**——`_record()` 根本不检查这个返回值。也就是说:代码路径上唯一能在"探针被正确调用、observation 构造正确"的前提下仍然完全不留痕迹的机制,就是这个有界队列的 fail-open 丢弃,与现象(无异常、无残留、无投影错误行,单纯"这条观测不存在")完全吻合。该 step 前后紧邻多条 `content.produced`/`context.snapshotted` 大 payload 观测(全库 `snapshot_visible_bytes` 达 7.4MB),时间点上具备造成队列瞬时打满的条件。
  3. **原诊断需校正,但本次实例仍无法实锤**:`AnsichService._dropped_count`/`_lost_ranges` 本体确是进程内存态,但并非“从不落盘”。`_persist_items` 成功后调用 `_report_degradation_if_storage_recovered`,按 `_reported_lost_range_count` 把未报告的 task-scoped range 转成 `observability.degraded` Observation;`assess_operations` 则把传入 range 写入运行中 Task 的 `ansich_active_task_read_model.lost_ranges_json`。前者只有**丢弃后又成功写入**才触发,后者会在重启后以空内存 range 重刷,所以两者都未覆盖“丢弃后立即重启”窗口。产生本次失败的 Gateway 进程已经重启,且当时日志已滚出,因此仍只能保留“高置信度、无法针对该实例 100% 确证”的结论。
- 方向(已落地):① 保持 fail-open 语义不变;② 在 core service 的 queue count/byte overflow 分支同步发一条带完整 batch range 的结构化 WARNING,并以 60 秒全局窗口限速,从而即使后续成功写入尚未发生就重启,operator 仍可从持久日志确认首个 drop 的时间、reason 与受影响 Task/range;日志 handler 失败也被吞掉且不改变业务返回;③ 把 loss 接入 U3 failed-job UI 仍延期,本次明确不做 UI。
- 归属:未定;由于机制上确认是"有界队列在设计上就会丢弃"而非代码 bug,不属于需要紧急修复的缺陷,但持久化 loss 可观测性这件事值得尽快做,否则同类问题会反复变成"猜测、无法实锤"。

## 评审中确认无需跟进的点(留档)

- **敏感字段三层拦截**:`AuthorizationSnapshot._bool_only_provider_has_no_permissions`、`ToolEffect._exclude_credentials`(`backend/packages/ansich/ansich/safety.py`)与 `ObservationEnvelope._validate_subject` 的全 payload `_find_secret_field` 扫描(`contracts.py`)三层独立拦截 JWT/cookie/API key/Authorization header 类内容,经直接代码走查确认。
- **`details_available=false ⇒ effective_permissions` 必须为空**由 `safety.py` 的 Pydantic validator 结构性保证,符合计划 §3;即便 H1 指出 `details_available` 目前恒为 `False`,该约束本身是稳固的,后续接入真实 provider 时可直接复用。
- **fail-open 边界**:`tool_middleware.py` 中所有 Ansich 记录调用均包在 `try/except: pass` 或返回 `False` 内;`AnsichRawToolMiddleware` 无论探针是否失败都会调用真实 `handler(request)` 并重新抛出原始异常(`except GraphBubbleUp: raise` + 兜底 `raise`),确认不改变 DeerFlow 真实执行结果。
- **`child_task_spawn` 不在 `_record_observed_effects` 产生**(tool_middleware.py:372-373 提前 return)——由 Phase 8 的 `TaskControlProbe.created()` 作为权威信号,正确避免了与 phase-8-review-followups.md M1(`wall_time_ms` 双写者)同类的双写陷阱。
- **`scope_safety.py::assess_scope_safety`** 在授权决策非 `allowed` 时正确拒绝产生 `attempted_scope_violation`/`realized_scope_violation`(`allowed_scope_ids` 保持为空,`outside_intents`/`outside_observed` 因此为空)——"unknown ≠ violation" 的要求被正确落实(该分支目前因 H1 而从未被生产数据触达,但领域逻辑本身是对的)。
- **迁移 `0020_ansich_scope_safety.py`**:upgrade/downgrade 对称,FK `CASCADE`/`RESTRICT` 语义合理,计划 §5 列出的四个索引(`(tool_call_id, evaluated_obs_id)`、`(decision, policy_id)`、`(effect_class, phase, scope_id)`、`(scope_id, tool_call_id)`)均已精确落地。
- **SQL 投影 `_project_authorization_snapshot`/`_project_tool_effect`**:幂等、对冲突重投影会 raise、通过 `_ProjectionDependencyPending` 正确等待被引用的 ToolCall/Scope 行——投影路径本身没有 M2 描述的重复计算问题(问题只在 assessor 读路径)。⚠️ **此前该条遗漏了 flush 顺序问题,已作为 H3 登记并修复**——幂等性/依赖等待判断本身仍然成立,但当时未核实"同一次 flush 内两个新对象的插入顺序"这一独立维度。

## 计划测试矩阵缺口(随修复补齐)

- ~~H1:`decision="unknown"` 在生产代码路径(而非手工构造的领域测试)零覆盖;`tool_middleware.py` 新增记录函数没有独立于 `AnsichExecutionContext`/`AnsichService` 集成路径之外的单元测试文件。~~ **已补齐(2026-07-21)**:`test_authorization_outcome.py` 独立单元覆盖桥接契约;`test_execution_context.py::test_raw_probe_records_unknown_when_no_guardrail_outcome` 让 `decision="unknown"` 首次在生产探针路径被断言。
- ~~H2:失败/超时/取消终态下具名工具(`write_file`/`bash` 等,而非 `_effect_class` 恒返回 `unknown` 的 `timeout_tool`)的 observed effect fidelity 零覆盖。~~ **已补齐(2026-07-23)**:`test_named_tool_failure_terminal_effects_are_not_hard_fidelity` 覆盖两个具名工具与三种非成功终态的完整组合。
- M1:`filesystem_delete`、`permission_change` 两个 effect class 零生产路径、零测试覆盖。
- M2:贡献/证据数增长时 scope-safety 重估工作量不随任务历史线性增长——尚无性能护栏测试(参考 phase-6-review-followups.md M1 的 SQL 监听回归写法)。
- API/UI:`test_ansich_router.py` 本次仅新增 26 行覆盖 4 个新端点,不足以独立确认 `_safe_effect_payload` 的敏感模式/绝对路径两个分支都被真实触达;建议补充针对性用例,尤其是 L1 的 Windows 路径分支。

# Phase 7 代码评审跟进项

来源:commits `37f8fa23`(assembly runtime descriptor)+ `17f3c308`(release 持久化与 drift 评估)+ `5f78a37a`(Release 查看/比较 UI)的代码评审(2026-07-19)。编号带 `M`(中)/`L`(低)优先级;修复一项后同步更新总览表和该项"状态"行,保留原始诊断记录。

## 状态总览

| 编号 | 摘要 | 状态 | 修复时间 | Commit |
| ---- | ---- | ---- | -------- | ------ |
| M1 | drift 判定对裸模型名一律 `unknown`,最常见的自托管漂移场景永不触发 mismatch | ✅ 已修复 | 2026-07-19 | `08cd6b1c` |
| M2 | P6 的 assessor coalescing 测试在全套件负载下时序性失败(flaky) | ✅ 已修复 | 2026-07-20 | `e91d9f1c`, `4e5eb0fd` |
| M3 | policy manifest 覆盖依赖属性探测,计划 §3 清单未被契约化,存在静默缺项 | ✅ 已修复 | 2026-07-20 | `256d2c91` |
| L1 | 计划 §5 的二线 credential validator 缺位(只有指纹校验,无 post-sanitization 模式检测) | ⬜ 未修复 | — | — |
| L2 | descriptor 经 `__pregel_runtime` 私有键传递,LangGraph 升级可能静默降级 | ✅ 已修复 | 2026-07-20 | `79cd13b1` |

## M1. drift 判定对裸模型名一律 `unknown`

- 状态:✅ 已于 2026-07-19 修复(commit `08cd6b1c`)。SQL assessor 现在显式传入 expected 来源：manifest `behavior_parameters.model` 视为 provider model，裸名不同判 `mismatch`，reported 以 expected + `-`/`.`/`:` 开头视为 revision match；只有回退到 registry alias 时不等仍判 `unknown`。normalization 语义变更同时将 assessor bump 到 `configuration-drift@1.1.0`，并用新 config hash 隔离历史规则。SQLite release 投影回归与领域三分类测试已覆盖 provider mismatch、revision match 和 alias unknown。
- 位置:`backend/packages/ansich/ansich/assessment/configuration_drift.py::assess_configuration_drift`(`elif expected is None or "/" not in expected or "/" not in reported: value = "unknown"`)+ `sql.py::_assess_configuration_drift_at`(expected 优先取 manifest `behavior_parameters.model`)。
- 现状:`mismatch` 分支只有当 expected 与 reported **都含 `/`** 时才可达。SQL 侧的 expected 优先使用 manifest 里的 provider model 字符串(`ModelConfig.model`,即实际发给 provider 的名字,不是 DeerFlow 注册 alias),此时两个裸名不相等是"明确不一致"——自托管 vLLM/SGLang 服务了与配置不同的权重、OpenAI-compatible 网关路由错模型,恰是计划 §7 要抓的运维场景,但都会被判 `unknown` 不告警。同时另一个方向也有误差:`"gpt-4o"` vs provider 报告的日期版本 `"gpt-4o-2024-08-06"` 也是 `unknown`,而它应当是 matched(revision)。注释里"裸名可能是 registry alias"的担忧只在 `behavior_parameters.model` 缺失、回退到 `model_summary.effective`(alias)时成立。净效果:该 assessor 与 `configuration_drift` Alert 在典型配置下几乎不可能产生 `mismatch`,功能核心近乎不可达。
- 方向:区分 expected 的来源——来自 `behavior_parameters.model`(provider 字符串)时启用裸名比较:相等或 reported 以 expected + 分隔符(`-`/`.`/`:`)开头视为 matched(revision),其余为 mismatch;仅当只能取 alias(provider 字符串缺失)时保持 unknown。normalization 规则变更需 bump assessor version(计划 §2)。配三类回归测试:裸名真不一致 → mismatch;日期 revision 后缀 → matched;alias 回退 → unknown。
- 归属:Phase 8 前完成(P8 子 Agent 树会把 drift 评估扩展到 subagent release,先把判定修对)。

## M2. assessor coalescing 测试在全套件下时序性失败

- 状态:✅ 已于 2026-07-20 完成修复(commits `e91d9f1c`, `4e5eb0fd`)。`e91d9f1c` 将计数 monkeypatch 与 SQL listener 移到 `service.start()` 之前，后台 projector 的首次 assessment 无法再在测试观测点就绪前消费 staged job，目标回归已连续通过 3 次。压力连跑又暴露出若干 SQL 集成测试会把套件负载下的暂态投影延迟误判为数据缺失；`4e5eb0fd` 将仅供直接 SQL 集成构造器的默认 settle 等待调为 10 秒，而生产 embedded 路径仍显式使用 `AnsichConfig.terminal_flush_timeout_ms=2000`，Agent 的有界 fail-open 语义未改变。
- 位置:`backend/tests/ansich/test_sql_alerts.py::test_sql_assessor_jobs_coalesce_to_highest_pending_watermark`(P6 commit `4f5ec989` 引入)。
- 现状:单测与文件级运行稳定通过,但全套件运行实测失败(1 failed / 289,断言 `evaluated_watermarks == [highest_watermark]` 一带)。根因:测试用 `operations_assessment_interval_ms=60_000` 推远后台评估,但 P5 的 projector 循环在 `service.start()` 后**立即执行首次 assessment**(`next_assessment = loop.time()`);全套件负载下事件循环调度延迟,首次后台 assessment 可能在测试安装 monkeypatch 之前就消化了 staged 的 assessor job,导致计数为空。这是 P6 测试的潜伏竞态,P7 扩大套件(233→290 项)后开始显形;违反"仓库强制 TDD、套件必须绿"的门槛,CI 将间歇性红。
- 方向:测试侧修复即可——在 `service.start()` **之前**安装 monkeypatch;或不启动后台循环(直接构造 backend、显式调用 `backend.assess_operations`);或给 service 加测试用的"首次评估延迟一个间隔"选项。修复后全套件连跑 3 次确认稳定。
- 归属:立即修复(它现在就能让 CI 变红)。

## M3. policy manifest 覆盖依赖属性探测,计划 §3 清单未契约化

- 状态:✅ 已于 2026-07-20 修复(commit `256d2c91`)。`runtime_descriptor` 现在优先消费 middleware 的 `release_policy_parameters() -> dict` 显式契约；无契约或第三方契约抛错时 fail-open 回退旧探测，并在新 manifest 的 `public_parameters` 中标 `probed=true`(不改 descriptor schema，历史 release fingerprint 可继续验证/重放)。summarization 显式声明 trigger/keep/prompt hash/summary-model identity，guardrail 声明 policy ID/version 与 effective provider rules，Tool output/token/loop/subagent-limit/deferred/todo/terminal/safety 策略也转为显式契约。lead assembly 从与执行相同的 subagent registry 产生 type allowlist 及逐类型 `max_turns`/`timeout_seconds`。Phase 7 §3 pin 测试固定 middleware order、summary/Tool output/token/loop/guardrail、subagent/plan/deferred 与 terminal/safety 路径，并验证 fallback marker 参与 policy hash。**自 `256d2c91` 起新 release 的 policy manifest 语义已修正，其 `policy_hash` 不可与该 commit 前的历史 release 直接比较。**
- 位置:`backend/packages/harness/deerflow/runtime_descriptor.py::_MIDDLEWARE_PUBLIC_FIELDS` / `describe_middleware`(hasattr 探测手工属性清单 + `_config` 侥幸抓取)+ `lead_agent/agent.py` 的 `effective_policies` 组装。
- 现状:policy_hash 覆盖 = middleware 链(顺序/类型名)+ 探测命中的属性 + 恰好存了 `self._config` 的中间件配置(token budget、tool output budget 因此覆盖)。但计划 §3 的 v1 清单里至少三项**不在** manifest 中:summarization 的 summary model identity(`self.model`/`_summary_model` 是模型对象,`_plain_value` 返回 None);guardrail/authorization policy ID 与 effective version(GuardrailMiddleware 未暴露探测属性);lead 链的 subagent `max_turns`/`timeout`(仅 subagent descriptor 的 policies 里有)。这些策略变更不会改变 release hash——"行为变化必产生新 release"的完成条件对它们不成立。反向风险同样存在:middleware 重命名/删除一个内部属性会静默改变所有新 release 的 policy_hash,没有任何测试会失败。
- 方向:把探测式采集改为显式声明——middleware 提供 `release_policy_parameters() -> dict` 协议方法(无该方法的 fallback 到现有探测并在 manifest 标注 `probed=true`);为 §3 的 v1 清单加一条 pin 测试,逐项断言对应值存在于 policy manifest 路径中,清单变化必须显式改测试。
- 归属:Phase 8 前完成(subagent release 会复用同一 descriptor 通道;越晚收紧,历史 release hash 的可比性越差)。

## L1. 二线 credential validator 缺位

- 状态:⬜ 未修复。
- 位置:`backend/packages/ansich/ansich/release/manifest.py::validate_agent_release`(仅指纹一致性)+ `::_sanitize`。
- 现状:计划 §5 要求"若 sanitized manifest 仍命中 credential field validator,release resolution 失败并发 observability.degraded"。现有防线:输入面 allowlist(model behavior 字段、middleware 属性清单)、字段名 denylist(`filter_secret_fields`)、known-secrets 精确值替换、runtime 地址清洗、MCP source 仅存 server name/transport——主层完整;但对最终 manifest **没有**主动的 credential 模式检测(高熵 token、URL userinfo、`Bearer ...`、`sk-` 形态),第三方工具 description/schema 里嵌入的凭据形态可以穿透落库并进 hash。resolution-failed → degraded 的失败通道已存在(`task_control.agent_release_resolved` 的 except 路径),只差把 validator 接上。
- 方向:在 `validate_agent_release`(或 `build_agent_release` 末尾)增加保守的 credential 模式扫描(URL userinfo、Authorization 头形态、常见 key 前缀 + 高熵启发),命中即抛错走既有 degraded 通道;配"含伪造凭据的 tool description 导致 resolution 失败且 Task 继续"的回归测试。
- 归属:Phase 9(Scope/授权与副作用审计)前完成——该阶段会扩大 manifest 类内容的采集面。

## L2. descriptor 经 `__pregel_runtime` 私有键传递

- 状态:✅ 已于 2026-07-20 完成修复(commit `79cd13b1`)。正常 lead worker 路径现在消费显式 `LeadAgentAssembly(graph, descriptor)` 返回值，descriptor 不再经 `__pregel_runtime` 往返；`make_lead_agent()` 继续保留 graph-only 公共兼容接口。Subagent 直接消费自身真实 assembly 产生的 descriptor，并通过显式 child `AnsichExecutionContext` 传递 Task 作用域。自定义 agent factory 若只返回 graph，worker 仍保留 graph attribute 兼容读取，但它已不再是内建 lead/subagent 的主通道。集成回归固定了 descriptor 经 Gateway factory → worker → `agent_release.resolved` 的真实路径。
- 位置:`lead_agent/agent.py::_publish_runtime_descriptor`(读 `config["configurable"]["__pregel_runtime"].context` 并写入)+ graph attr 兜底 + `worker.py` 的两路读取。
- 现状:`__pregel_runtime` 是 LangGraph 的私有实现细节;版本升级重命名/改变注入时机会静默断掉 runtime-context 路径。graph attr 兜底(`setattr(graph, ...)`)仍在,但对 CompiledGraph setattr 同样不是公开契约。降级路径正确(缺 descriptor → `observability.degraded`,不阻塞 Run),因此是脆弱点而非故障;但一次依赖升级就可能让所有 Task 静默失去 release 绑定,只有细看 health 才会发现。
- 方向:加一条"descriptor 经 worker 真实路径可达"的集成回归(升级 LangGraph 时会红);或改用自有的显式通道(例如 assembly 返回值直接传给 worker,而不是经 config 往返)。
- 归属:Phase 8 前顺带处理(P8 会在 subagent 执行路径上再走一遍同样的传递)。

## 评审中确认无需跟进的点(留档)

- **单源 assembly**:`_assemble_lead_agent` 把同一批 model/middlewares/system_prompt/final_tools 同时交给 `create_agent` 与 descriptor,无平行推导;`make_lead_agent()` 兼容接口保留(`.graph`);bootstrap 与常规路径都覆盖。
- **canonicalization 单一实现**:`release/canonical.py` 直接复用 `assessment/base.canonical_json_bytes`,没有第二套 canonical JSON(遵循了 P6→P7 衔接指令)。
- **不可变性三层防线**:release 实体按确定性 ID(namespace/agent/release_hash)去重;同 ID 不同指纹拒绝;manifest payload 字节级不可变;Task 绑定(`ansich_task_agent_releases`)改绑拒绝;`executed_by` relation + evidence 幂等。
- **失败通道**:resolution 失败与 descriptor 缺失都发 `observability.degraded`,Task 继续执行,不为 release completeness 阻塞 Run——符合 §5。
- **provider_model 采集修正**:`llm.requested` 不再把 configured model 误存为 provider_model;`llm.responded` 从 provider report / response_metadata.model_name 取值,多 attempt 全部保留为 evidence,release hash 不受影响。
- **API/UI 边界**:list/detail 剥离 rendered prompt(`_redact_release_prompt`),完整 manifest 走独立端点(admin + 访问日志含 actor + `Cache-Control: no-store`);compare 由后端产 typed diff,tool 按 `(source, name)` 键匹配,同名不同 source 不误判;quality 恒为 `unassessed`。
- **drift 与 Alert 通道衔接**:`configuration_drift` 复用 P6 的 assessment→assertion→episode 机制,job 走同一 coalescing 通道;前端把它加入公开类型常量(与 P6-L4 "只广告有生产者的类型"决策一致,现为 7 类)。
- **协议扩展先补文档**:`agent_release.resolved` kind 已在本切片同步写入 `ansich-design-document.md`(计划 §6 的前置要求满足);迁移 `0018_ansich_agent_releases` 幂等、downgrade 完整;subagent executor 同步产出 descriptor 为 P8 铺路。
- `tests/ansich` + 新增 lead-agent resolution 测试共 290 项,除 M2 的套件级 flake 外全部通过;`test_release_manifest.py` 覆盖 §10 的 canonical/fingerprint/sanitization(改 API key 不改 hash、改行为参数改 hash)/immutability 矩阵。

## 计划测试矩阵缺口(随修复补齐)

- M1:裸名 mismatch / revision 后缀 matched / alias unknown 三分类。
- M2:全套件连跑稳定性(修复后 3 连跑验证)。
- M3:§3 v1 清单 → policy manifest 路径的逐项 pin 测试。
- L1:伪造凭据穿透 sanitization 时 resolution 失败 + Task 继续。
- L2:✅ 显式 assembly 返回值与 worker 真实 release 绑定路径已覆盖；仅保留自定义 graph-only factory 兼容兜底。

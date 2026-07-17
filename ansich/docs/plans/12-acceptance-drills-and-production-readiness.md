# Phase 12 — 验收演练与生产就绪

## 1. 交付目标

本阶段不再扩展世界模型，而是证明前十一阶段组合后满足设计约束，并建立可重复的上线、回滚和运维基线。验收必须使用真实 DeerFlow 路径、SQLite/PostgreSQL、故障注入和安全扫描；不能用单元测试数量代替端到端证据。

已确认的范围：真实 runaway/drift failure paper drill 仍需完成；语义错误 paper drill 按当前决定暂缓，记录为 owner 接受的 known gap，不伪造样本，也不在本阶段临时引入错误 oracle。

## 2. 验收数据集与固定场景

建立 `backend/tests/ansich/fixtures/scenarios/` 的脱敏 fixture 和可生成脚本，至少包含：

1. 正常无 Tool 直接回答。
2. 单 Step 多个并行 Tool。
3. provider/adapter retry 后成功。
4. Tool denied、failed、timeout、cancelled、raw/visible 变化。
5. context compression，含 source/preserved/removed。
6. 长时间 Tool，期间只有 outer heartbeat。
7. exact-signature loop 和绝对 budget breach。
8. 30 个不同 search query 的高频但成功 Task。
9. child subagent 成功/失败/parent cancel。
10. Scope violation intent、deny、observed effect 和 unknown bash/MCP effect。
11. external benchmark evaluation 和无 evaluation release。
12. collector/store/projector/retention 故障。

fixture 不能包含真实用户 prompt、credential、绝对个人路径或现有本地数据库的完整 Run UUID。来自真实 Run 的 fixture 要有 provenance 说明、脱敏 manifest 和 expected world-model assertions。

## 3. 两项 paper drill 的处理

### 3.1 必做：真实 runaway/drift failure

从真实失败 Run 选择一个已获授权的记录，完全用 v0.2 词汇叙述：Task/AgentRelease/Step/attempt/ToolCall/ContextSnapshot/ContentBlock/Belief/Alert/Scope/effect。输出放入 `ansich/docs/drills/`，并逐项回答：

- earliest 直接可观测异常是什么；
- 哪个 rule assertion 支持 runaway/drifting；
- evidence window 和 lost ranges 是什么；
- 哪些后续 Step 只是 possible exposure；
- operator 当时能执行 interrupt 还是 rollback；
- 当前 schema 是否缺少必要概念。

若出现 v0.2 无法表达的概念，先修订设计和受影响阶段，再通过 drill；不能在 drill 中自创无 schema 字段。

### 3.2 暂缓：语义错误 expected-vs-actual

本阶段只登记：缺少经授权的真实 Run 与外部 oracle；Phase 10 已保留 evaluation 入口；该 drill 由 owner 明确延期。不得拿 Task failed、用户负反馈或 LLM 自评冒充 expected-vs-actual。未来样本到位时单独补 drill 并重新评估 D2/D3 验收。

## 4. 端到端不变量测试

编写一个 black-box harness，通过 Gateway 创建 Run 并只从 Ansich API 验证：

- 顶层 Task 与 run_id 一一映射；child Task 树独立。
- Agent Step 与 system operation 分离；retry 不增加 Step。
- effective request 可重建结构化 inventory 且无 secret。
- Tool intent/raw/visible/auth/effect 链完整；provider ID 重用不冲突。
- backward lineage 和 possible exposure 有界且可解释 compression。
- state 均为完整 Belief；unknown/unassessed 不被省略。
- exact repetition 产生 runaway；changing-query frequency 不产生 runaway。
- local/inclusive usage 无双计，budget source/enforcement 准确。
- AgentRelease component 变化与 diff 准确。
- Alert action 最终调用 DeerFlow 真实 interrupt/rollback 语义。

这些断言在 SQLite 和 PostgreSQL 各跑一次。PostgreSQL 再以两个 Gateway/projector worker 运行 lease 竞争场景。

## 5. 性能与容量基线

使用可重复 load profile 记录：每秒 Observation、平均/峰值 payload、queue depth、batch size、DB 写吞吐、projector lag、API p50/p95/p99、启用 Ansich 前后 Run 首 token/总耗时差。

建议初始 release gate（最终数值由基准机校准并写入文档）：

- 正常小 payload 下 `Collector.record()` p99 不超过 1ms 且不做同步 DB I/O。
- 目标吞吐下 queue 无持续增长，projector p95 lag 低于 Operator minute-level SLA。
- Task 列表和单 Step detail 在基准数据量下 p95 低于 500ms。
- lineage 达到 500-node 硬上限时有界返回，不触发全表扫描。
- 启用 Ansich 不显著改变 Agent 成功率；性能差异超门槛必须阻断默认启用。

用 `EXPLAIN` 确认高频查询命中计划中的 typed 索引；SQLite/PostgreSQL 分别保存 query plan 摘要。

## 6. 安全与隐私验收

构造 canary secrets 覆盖 header、cookie、env、DSN、Tool args/result、prompt、MCP config、request-scoped secret。扫描 `ansich_observations`、`ansich_payloads`、AgentRelease manifest、projection/read model、日志和前端 network/cache，任何原值命中均阻断发布。

验证：

- 所有 Ansich endpoint admin-only，普通用户/匿名无 metadata side channel。
- raw payload 访问有成功/拒绝审计，audit DB down 时 fail-closed。
- response 和浏览器使用 no-store，不写 localStorage。
- owner/thread 删除清除全部相关层；retention tombstone 不含原内容。
- path/target preview 只显示受控 logical value。
- payload size、lineage depth/node、pagination limit 均有服务端硬上限。

## 7. 故障与恢复演练

逐项注入并记录预期/实际：

- Collector queue full。
- payload serialization failure。
- SQLite locked/PostgreSQL disconnect。
- Batch transaction 中途失败。
- projector crash、lease takeover、poison job。
- Gateway 收到 shutdown 时有 Run/queue/projector transaction。
- payload retention 与 owner 删除并发。
- active resolver/projector version 配置错误。

每个场景必须证明两件事：DeerFlow Task 结果不因 Ansich 故障改变；Ansich health/Task projection 明确显示 degraded、failed、lag 或 lost range。若无法确定 lost range，显示 unknown，不能通过日志文字替代 API 证据。

## 8. 前端验收

Playwright 覆盖 `/workspace/ansich/operations` 与 Task detail 全部标签：active polling、terminal stop、unknown/unassessed、Alert evidence、action 确认、release diff、Task tree、lineage truncated、raw lazy read、403/503/degraded。

使用大 Task/500-node lineage 验证页面不一次性 fetch raw payload、不阻塞主线程、不因轮询重置用户展开状态。检查键盘导航、表格 fallback、颜色之外的状态文案和时间/数字本地化。

## 9. 配置、文档与发布

同步修改：

- `config.example.yaml`：全部 Ansich startup-only 配置和安全默认值。
- 根 README：启用方式、仅 dev/op admin audience、内嵌部署。
- `backend/AGENTS.md`：包边界、probe 链、迁移/测试、fail-open 规则。
- `frontend/AGENTS.md`：Ansich routes、TanStack Query polling 和 raw cache 限制。
- 运维文档：health 字段、Alert 含义、interrupt/rollback 差异、retention/replay 命令。
- 架构文档：实际文件路径、projector/resolver versions 和已接受 known gaps。

发布采用三步：默认关闭 → 指定 dev/op 环境显式启用并观测 → 满足基线后再讨论默认启用。每步定义回滚：关闭 `ansich.enabled` 并重启停止新采集；保留表供诊断；不删除 Observation。schema migration 必须向前兼容至少一个应用版本，避免 rolling deploy 中新旧 worker 互相破坏。

## 10. 最终执行清单

- `cd backend && make format`
- `cd backend && make lint`
- `cd backend && make test`
- backend blocking-I/O suite 覆盖新增 async 路径
- SQLite/PostgreSQL migration + replay + multiworker integration
- `cd frontend && pnpm test`
- `cd frontend && pnpm check`
- `cd frontend && pnpm test:e2e`
- secret canary scan、owner deletion、raw audit tests
- load/performance/query-plan 基线
- real runaway/drift paper drill
- README/AGENTS/config/operations docs review

测试失败不得以“观测功能不影响主流程”为理由忽略；fail-open 只规定运行时故障语义，不降低发布质量门槛。

## 11. 完成条件

- 十二个固定场景在 SQLite/PostgreSQL 端到端通过，PostgreSQL 多 worker lease 通过。
- 所有设计不变量均能从 API 证据验证，而不是人工查日志。
- fail-open、degraded/lost range、raw read fail-closed 均经过故障注入。
- canary secret 在任何存储/响应/缓存中零命中。
- 真实 runaway/drift drill 完成且没有未处理的 world-model 缺口。
- 语义错误 drill 按 owner 决定保持显式延期，Phase 10 入口与 known gap 文档完整。
- 发布默认保持关闭，具备明确启用、观测和回滚步骤。

# Ansich v1 分阶段实施计划

本目录把 [Ansich v0.2 设计](../ansich-design-document.md) 拆成十二个可独立执行、可独立验收的阶段。阶段按顺序交付，每个阶段都必须形成一条可运行的纵向切片，而不是只提交数据表、只提交探针或只提交页面。

## 当前实施状态（2026-07-20）

- Phase 1 已形成可运行纵向切片：嵌入式启动、Run→Task 生命周期、严格 Observation 契约、有界 fail-open Collector、Observation/job 原子写入、独立 leased projector、Task/Scope/Belief 投影、重放、管理员 API，以及 dev/op 工作区列表和详情页均已实现。
- SQLite、Gateway、Run worker、API、前端类型/lint、前端全量单测，以及管理员列表→Task 详情和 503 的真实浏览器 E2E 已经验证；Phase 1 尚未标记最终完成，因为 PostgreSQL 集成矩阵、关闭 Ansich 的基准对比和生产环境 paper drill 仍待执行。
- Phase 2 已形成可运行的本地纵向切片：逻辑 Step 与 adapter attempt 分层、内部 LLM system operation、有序模型输入快照、payload 分层、SQL 投影/API，以及 Operations 的 Timeline/Steps/Context 页面均已实现。SQLite、相关后端回归、前端全量单测和真实浏览器 E2E 已验证；PostgreSQL 迁移矩阵、关闭 Ansich 的性能基准和生产 paper drill 完成前不标记最终完成。
- Phase 3 已形成可运行的本地纵向切片：Tool intent、raw callable boundary、模型可见结果和 unknown/denied authorization attachment point 分离；Task terminal reconciliation、重启恢复、typed SQL 投影、issued/executed usage、管理员 API 以及四段责任链页面均已实现。SQLite migration/rebuild、后端 Ansich 回归、前端类型/lint 和 raw/visible 权限边界已验证；PostgreSQL 迁移矩阵与生产负载演练仍属于后续生产就绪门禁。
- Phase 4 已形成可运行的本地纵向切片：typed producer/derivation 表、纯 BFS 谱系遍历、压缩前冻结的 source/preserved/removed inventory、summary block 与 `compressed` 边、snapshot 反向 membership、metadata-only 的 lineage/exposure/snapshot/compression API 以及 Context & Lineage 页面均已实现（详见 [04-context-lineage-and-compression.md](04-context-lineage-and-compression.md) 的实现状态）。PostgreSQL 迁移矩阵、关闭 Ansich 的基准对比和生产 paper drill 完成前不标记最终完成。
- Phase 5 已形成可运行的本地纵向切片：owner-only Outer Run heartbeat、完整 rule Belief、local Usage、实际 runtime Budget 快照、`0016_ansich_operations` 投影/重放、active-task read model、管理员 API 与自适应轮询 Operator Lens 已落地（详见 [05-active-tasks-heartbeats-and-budgets.md](05-active-tasks-heartbeats-and-budgets.md)）。SQLite migration/rebuild、PostgreSQL DDL 语义、后端与前端回归已覆盖；真实 PostgreSQL 升级矩阵、关闭 Ansich 的基准和生产 paper drill 仍是最终生产就绪门禁。
- Phase 7 已形成本地完整闭环：lead/subagent 实际 assembly 产出 runtime descriptor，Task admission 解析并绑定不可变 AgentRelease，typed projection/API 支持 release 查询与结构化比较，provider-reported model 作为 attempt evidence 驱动 `configuration_drift` Belief/Alert，Task 详情可查看脱敏配置、组件哈希和 release diff（详见 [07-agent-release-and-comparison.md](07-agent-release-and-comparison.md)）。SQLite 迁移、PostgreSQL DDL 编译、后端 Ansich 回归、前端类型/单元检查与关键 Playwright 流程已覆盖；真实 PostgreSQL 升级矩阵、关闭 Ansich 的基准和生产 paper drill 仍是最终生产就绪门禁。
- Phase 8 已形成本地纵向切片：实际 subagent 委派产生独立 child Task/context/release/probes/heartbeat，typed spawn 与 ancestry closure 支持多层树和环/第二 parent 防御，source-aware contribution 投影提供 local/inclusive Usage、late relation backfill 与可解释 source breakdown；tree/children/scoped usage/root-only API 及 Task tree、Budget scope、lineage child link UI 已落地（详见 [08-subagent-task-tree-and-inclusive-usage.md](08-subagent-task-tree-and-inclusive-usage.md)）。migration `0019_ansich_task_tree_usage` 覆盖历史 self usage 转换与 read-model 重建；真实 PostgreSQL 升级矩阵、关闭 Ansich 的基准和生产 paper drill 仍是最终生产就绪门禁。
- Phase 9 已形成本地纵向切片：多 Scope/role/evidence、不可变 AuthorizationSnapshot、potential/intended/observed Effect、`scope-safety@1` conclusion/Alert、`0020_ansich_scope_safety` typed SQL 投影与 replay、管理员 API 及 “Scopes & effects” UI 已落地（详见 [09-scope-authorization-and-effects.md](09-scope-authorization-and-effects.md)）。unknown coverage 保持显式，Ansich probe fail-open 且不改变 DeerFlow 授权决定；真实 PostgreSQL 升级矩阵、关闭 Ansich 的基准和生产 paper drill 仍是最终门禁。
- Phase 10 已形成本地纵向切片：`evaluation.recorded` v1 契约与唯一 core validator（verdict/score+scale、hard fidelity 只对带 suite/case 的 benchmark/unit test 开放、`earliest_erroneous_step` 必须指名本 Task 的 Step）、升级到 `ansich-default@2.0.0` 的 Belief resolver（新增 `soft_human` 档，v1 逐字保留可按版本重放）、migration `0023_ansich_evaluations` 的 `ansich_evaluation_index` 与 `ansich_release_quality_stats`、`evaluation-projector@1`（索引行 + `quality.<dimension>` assertion + 按格加锁重算的 release 聚合）、五个具名维度的 unassessed 合成、record/read 服务面与 cohort 可比性规则，以及 Gateway 的评估录入/读取/release quality/审计 no-store payload 端点、compare 的 quality 区块、feedback→evaluation 的 fail-open 桥接和 Task 详情第五个入口 `?view=evaluations` 与 release 比较 Quality 卡片均已落地（详见 [10-evaluation-and-semantic-beliefs.md](10-evaluation-and-semantic-beliefs.md) 的实现状态）。本地验收覆盖 SQLite 迁移/重放、后端 Ansich 回归（430 项）与前端 lint/typecheck 及单元测试（804 项）；真实 PostgreSQL 升级矩阵、关闭 Ansich 的性能基准和生产 paper drill 仍是最终生产就绪门禁。Phase 11–12 尚未开始实现。
- Phase 1 代码评审的跟进项登记在 [phase-1-review-followups.md](phase-1-review-followups.md)，各项带有修复状态、归属阶段与对应 commit；Phase 2 的实施前提 F4（projector 显式优先级）已修复。
- Phase 2 代码评审的跟进项登记在 [phase-2-review-followups.md](phase-2-review-followups.md)；H2（上下文快照写放大与谱系完整性）的剩余压缩 inventory 与 derived-from 边已随 Phase 4 commit `a596a310` 落地，现已完成。
- Phase 3 代码评审的跟进项登记在 [phase-3-review-followups.md](phase-3-review-followups.md)；M2（transform 显式元数据）与 M3（队列字节水位）均已完成，Phase 5 前置项已清；L1 观察开销基准按既定归属留到 Phase 12 验收前，不阻塞 Phase 5。
- Phase 4 代码评审的跟进项登记在 [phase-4-review-followups.md](phase-4-review-followups.md)；M1/M2/M3、L1/L2 与 L3①/② 均已完成；L3② 的前端压缩列表独立 API 已作为 Phase 6 首批 UI/API 工作落地。
- Phase 5 代码评审的跟进项登记在 [phase-5-review-followups.md](phase-5-review-followups.md)；M1/M2/M3 与 L1/L2 均已修复，L3（usage 贡献契约收紧）也已由 `fe4634bf` 修复，Phase 8 前的 Phase 5 到期项已清。
- Phase 6 代码评审的跟进项登记在 [phase-6-review-followups.md](phase-6-review-followups.md)；L3（wall_time 覆盖语义）已由 `b910ba82` 修复，M1（assessor job 合并）与 L1（对账读放大）已由 `4f5ec989` 修复；L4 已由 `0a38a96d` 明确延后到 Phase 11 并隐藏未生产类型。Phase 7 开工前置项已清；L2（孤儿 requested action 回收）仍按原归属留到 Phase 11 前。
- Phase 7 代码评审的跟进项登记在 [phase-7-review-followups.md](phase-7-review-followups.md)；M2（coalescing 测试套件级 flaky）已由 `e91d9f1c`/`4e5eb0fd` 修复并隔离 SQL 集成测试 settle 时序，M1（drift 裸名判定）已由 `08cd6b1c` 修复，M3（policy manifest 契约化）已由 `256d2c91` 修复，L2（descriptor 私有通道回归）已随 Phase 8 的显式 assembly/context 通道由 `79cd13b1` 完成；L1（二线 credential validator）已于 Phase 9 开工前随本次提交完成。
- Phase 8 代码评审的跟进项登记在 [phase-8-review-followups.md](phase-8-review-followups.md)；M1（wall_time 双写者）与 M2（heartbeat contribution 写/读放大）均归属 Phase 11 前的 wall_time 通道治理,L1（吞 CancelledError）与 L2（tree N+1）随相关路径下次改动顺带处理,均不阻塞 Phase 9 开工。
- 非评审来源的人工发现跟进项登记在 [human-followups.md](human-followups.md)；各项附施工时机评估（D1 概念词汇表立即做，U3 failed-jobs 下钻与 U4 compression 执行时机可随 Phase 9 提前，U1/U2/A1 分别归属 Phase 10 后与 Phase 11），每个 Phase 开工前复查该文件。
- Phase 9 代码评审的跟进项登记在 [phase-9-review-followups.md](phase-9-review-followups.md)；H1–H7 均已修复，其中 H6 让 scope-safety assessor 在 subject ToolCall Entity 尚未投影时无 attempt 等待并可自愈（等待带持久化 `dependency_pending_since` 锚点并复用 `projector_dependency_timeout_seconds` 上界，subject 永不出现时越界转 durable failed 进入 failed-job 重试诊断面，迁移 `0022_ansich_assessor_deadline`），H7 在保留 Collector fail-open 语义的同时补齐 queue count/byte overflow 的限速结构化持久日志，并校正了既有 `observability.degraded`/active read model 部分持久化路径的边界。M1（effect class 分类法缺 filesystem_delete/permission_change）与 M2（scope-safety assessor 全量重扫）归属 Phase 11 前治理，L1/L2 为非阻塞清理项，均不阻塞 Phase 10 开工。
- 回溯验证矩阵登记在 [retro-validation-matrix.md](retro-validation-matrix.md)：六个故障注入用例分别对应 upstream 已关闭 issue（#3320/#4041、#3684、#4176、#3875、#3113、#3645），检验 Observation→Belief 是否足以独立判定这六类错误。预测在跑测试**之前**已预注册，结果表记录实际判定与差异。结论：零失败项，一笔弱通过（#3645 缺 by-model 聚合查询，证据齐全），一处能力边界确认（bash 无 instrumentation，`coverage="unknown"` 属设计使然）。测试位于 `backend/tests/ansich/test_retro_*.py`，共享 harness 在 `backend/tests/support/ansich_retro.py`。

## 固定实现边界

以下决策适用于全部阶段，若实现中需要改变，必须先修订设计文档和受影响的阶段计划：

1. `backend/packages/ansich/` 是独立 Python 包，放置 Observation、Entity、Belief、Relation 等领域契约，以及不依赖 DeerFlow、LangGraph、FastAPI 的投影和查询逻辑。
2. `backend/packages/harness/deerflow/ansich/` 是 DeerFlow 适配层，放置 SQLAlchemy 表、仓储、Gateway 进程内服务装配和运行时探针。依赖方向只能是 `deerflow -> ansich`。
3. `backend/app/gateway/routers/ansich.py` 只做认证、请求校验、DTO 转换和调用应用服务，不在路由中写投影或规则逻辑。
4. `frontend/src/core/ansich/` 负责 API 类型、TanStack Query hooks 和纯转换函数；`frontend/src/app/workspace/ansich/` 与 `frontend/src/components/workspace/ansich/` 负责页面和组件。
5. Ansich 与 DeerFlow 共用已配置的 SQLAlchemy Engine/SessionFactory，但只写 `ansich_*` 表，不修改 `run_events` 语义。
6. 所有采集失败均 fail-open；现有 Token、循环、授权、超时等 DeerFlow 执行保护仍在本地同步路径中 fail-safe。
7. 除 Observation/Payload 外，Entity、Belief、Relation、Usage 和 Read Model 都是可删除、可按 projector version 重放的投影。
8. 后端实现强制 TDD。每个阶段先提交失败测试，再实现；SQLite 和 PostgreSQL 语义都要覆盖。前端新增行为必须有 unit test，关键操作流必须有 Playwright E2E。

## 阶段索引

1. [第一条可观测 Task](01-first-observable-task.md)
2. [逻辑 Step 与实际模型输入](02-logical-steps-and-model-inputs.md)
3. [ToolCall 责任链](03-toolcall-accountability.md)
4. [上下文谱系与压缩](04-context-lineage-and-compression.md)
5. [活动任务、心跳与预算](05-active-tasks-heartbeats-and-budgets.md)
6. [失控告警与干预](06-runaway-alerts-and-intervention.md)
7. [AgentRelease 与版本比较](07-agent-release-and-comparison.md)
8. [子 Agent Task 树与 inclusive usage](08-subagent-task-tree-and-inclusive-usage.md)
9. [Scope、授权与副作用审计](09-scope-authorization-and-effects.md)
10. [评估输入与语义 Belief](10-evaluation-and-semantic-beliefs.md)
11. [生产韧性、重放与保留策略](11-resilience-replay-and-retention.md)
12. [验收演练与生产就绪](12-acceptance-drills-and-production-readiness.md)

## 阶段合并规则

每个阶段完成时必须同时满足：

- 迁移可在空 SQLite、已有 SQLite、空 PostgreSQL、已有 PostgreSQL 上执行；降级策略有明确说明。
- 新增 Observation kind 有 schema version、幂等 source event ID 生成规则和至少一个重复/乱序测试。
- 新增状态字段返回完整 Belief 结构，不允许 API 暴露裸状态枚举。
- UI 显示投影时间、丢失范围或 `unknown`/`unassessed`，不把资料缺失展示成健康或零值。
- 失败注入证明 Ansich 不改变 DeerFlow Run 的业务结果。
- 相关 README、`backend/AGENTS.md`、`frontend/AGENTS.md` 与配置示例同步更新。

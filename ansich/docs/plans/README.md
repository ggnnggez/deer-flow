# Ansich v1 分阶段实施计划

本目录把 [Ansich v0.2 设计](../ansich-design-document.md) 拆成十二个可独立执行、可独立验收的阶段。阶段按顺序交付，每个阶段都必须形成一条可运行的纵向切片，而不是只提交数据表、只提交探针或只提交页面。

## 当前实施状态（2026-07-17）

- Phase 1 已形成可运行纵向切片：嵌入式启动、Run→Task 生命周期、严格 Observation 契约、有界 fail-open Collector、Observation/job 原子写入、独立 leased projector、Task/Scope/Belief 投影、重放、管理员 API，以及 dev/op 工作区列表和详情页均已实现。
- SQLite、Gateway、Run worker、API、前端类型/lint、前端全量单测，以及管理员列表→Task 详情和 503 的真实浏览器 E2E 已经验证；Phase 1 尚未标记最终完成，因为 PostgreSQL 集成矩阵、关闭 Ansich 的基准对比和生产环境 paper drill 仍待执行。
- Phase 2–12 尚未开始实现；页面不得提前显示 Step、ToolCall、进度百分比、预算或语义判断的占位数据。
- Phase 1 代码评审的未决跟进项登记在 [phase-1-review-followups.md](phase-1-review-followups.md)，各项已标注归属阶段；其中 F4（projector 显式优先级）是 Phase 2 的实施前提。

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

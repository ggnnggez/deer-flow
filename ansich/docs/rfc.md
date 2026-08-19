# RFC: Ansich —— DeerFlow 的 Agent 执行可观测层

> 状态：提案 · 基准 `upstream/main@5f0108f5` · 2026-07-25
>
> 本文只讲动机、抽象与边界，不含实现细节。数据模型与协议见
> [ansich-design-document.md](ansich-design-document.md)，概念定义见
> [concepts.md](concepts.md)，分阶段施工见 [plans/README.md](plans/README.md)。

## 1. 为什么需要

DeerFlow 今天有三条记录：checkpoint（状态快照）、`run_events`（面向前端回放）、外部
tracing（模型/工具调用）。三者都答不出运维与开发者最常问的问题：**这次运行究竟发生了
什么、模型真正看到了什么、"成功"的判断依据是什么**。

根因是 `run.status`、`subagent_status` 这类**单一可变字段把"事实"和"判断"混在一起并覆盖式
写入**，事后无法复算，也无法区分"没发生"与"没采集到"。

## 2. 核心抽象与功能

三层严格分离：

| 层 | 内容 | 性质 |
|---|---|---|
| **Observation** | 采集到的不可变事件 envelope | 唯一事实来源，append-only、幂等 |
| **事实读模型** | Task / Step / LLM attempt / ToolCall / ContentBlock / ContextSnapshot / Usage / Scope | 幂等投影，可删可按版本重建 |
| **Belief** | assessor 在明确 watermark 下产出的版本化判断 | 带 evidence、authority/fidelity、config hash；current belief 由 resolver 选出，不覆盖历史 |

三条不可协商的规则：**fail-open**（采集失败绝不改变业务结果）、**append-only**（纠错靠新事实）、
**`unknown` 是一等值**（不能用缺行或默认 false 冒充）。

## 3. LangSmith / Langfuse 的边界

它们是 span 树，回答"哪次调用、耗时、输入输出"。不回答：

- 逻辑 Step 与物理 attempt 的分层（重试不覆盖旧 attempt；title/summarization 等系统操作不占决策步）；
- 某次请求**真正可见的有序上下文清单**，及 memory / summary / skill 注入的来源标记；
- 内容谱系：raw 结果 → 净化 → 截断 → 摘要的派生边；
- 归属：local 与 inclusive usage、按子 Task 拆分的 source breakdown；
- 判断的**可复算性**：结论带 assessor 版本与证据，可重放重算。

且两者是外部 SaaS，prompt 正文离开进程；Ansich 只存 hash/preview，正文经独立审计路由读取。

## 4. 已发生的对应问题（upstream 已关闭 issue）

| 类别 | issue |
|---|---|
| 拿不到原始轨迹 / 观测不足 | #2871、#3116、#3126、#4243、#3550 |
| 失败被静默判成功 | #3320（provider 失败→success）、#4041（子 agent 400→completed）、#4027（空终态→success）、#4176（50×bash 强停仍 success） |
| 归属与计量错误 | #3645（token 全算到 lead 模型）、#2734、#3875（子 agent 烧 4.4M token）、#3113 |
| 失控无信号 | #3122 |
| 上下文生命周期难查 | #3684、#3725、#3352 |

其中 **#3550 列出的四个问题与 Ansich 上下文谱系能力逐条对应**，#3116 的诉求与
active-task / usage / budget 读模型一致。

## 5. 有了 Ansich 会怎样

- **静默成功类**：ToolCall 的授权/执行/可见结果是三个各带证据的独立读模型；attempt 的
  requested/responded/failed 分开保留；Task summary 把 issued 与 executed 分别计数。
  "run=success 但无产出且 50 次 bash"这类组合在读模型中直接成立。
- **归属类**：usage contribution 幂等键为 `(source_obs_id, dimension)`，rollup 只消费
  contribution，重复计数在结构上不可能；每个子 Task 有独立 AgentRelease，按模型拆分是天然的。
- **上下文类**：ContextSnapshot 保序记录成员清单，配合内容派生边，可回答"两次调用收到的
  memory 是否字节相同"。

明确的**非目标**：Ansich 不改 `run.status`，不阻断执行，不替代 `run_events`；工具缺乏
instrumentation 时记 `unknown`，绝不推断副作用。

## 6. 对外接口概览

全部挂在 `/api/ansich`，共 44 个端点（38 GET / 6 POST），统一由 `require_admin_user`
保护；`ansich.enabled` 关闭或存储不可用时返回 503，仅 `GET /health` 在存储不可用时
仍可读。按职责分八组：

| 组 | 代表端点 | 说明 |
|---|---|---|
| Task 导航 | `/tasks`、`/tasks/{id}`、`/children`、`/tree`、`/scopes` | 列表支持 lifecycle scope、游标与 root-only |
| 执行轨迹 | `/tasks/{id}/timeline`、`/steps`、`/steps/{id}/context`、`/context-snapshots/{id}` | 逻辑 Step 与物理 attempt 分层，快照保序 |
| ToolCall 责任链 | `/tool-calls/{id}`、`/authorization`、`/effects` | 授权、执行、可见结果各自独立且带证据 |
| 内容与谱系 | `/content-blocks/{id}/lineage`、`/exposures`、`/context-compressions/{id}`、`/tasks/{id}/context-compressions` | metadata-only，不含正文 |
| 计量与预算 | `/tasks/{id}/usage?scope=local\|inclusive`、`/budgets` | 带来源拆分与健康 Belief |
| AgentRelease | `/agent-releases`、`/{id}`、`/compare?cohort=` | 不可变绑定、结构化比较与同 cohort 的质量比较 |
| 评估与质量 | `POST /evaluations`、`/tasks/{id}/evaluations`、`/steps/{id}/evaluations`、`/agent-releases/{id}/quality?cohort=`、`/evaluations/{obs_id}/payload` | 外部评估录入与语义 quality Belief；未评估维度显式 `unassessed` |
| 运维 | `/operations/active-tasks`、`/alerts*`、`/safety-events`、`/failed-jobs*`、`/tasks/{id}/actions/{interrupt,rollback}`、`/health` | 主要的写入面 |

三条接口约定：

- **读写分离**：6 个 POST 中 5 个集中在运维组（告警 acknowledge / dismiss、失败作业重试、
  Task interrupt / rollback），且都不写业务数据——interrupt / rollback 是对 `RunManager`
  的受审计代理，要求 `Idempotency-Key`。第 6 个 `POST /evaluations` 只写 Ansich 自己的
  Observation，同样要求 `Idempotency-Key`。
- **正文隔离**：默认只返回 metadata 与 preview；完整 release manifest、tool raw/visible
  结果、ContentBlock payload 与 evaluation 的 expected/actual/rationale 走四条独立的
  `Cache-Control: no-store` 路由并记审计日志。
- **降级可见**：`/operations/active-tasks` 以 ETag + 游标轮询，ETag 只覆盖数据项与游标、
  不含易变的投影健康；投影缺失的行返回 degraded，而不是短页或零值。

## 7. 对 main 的入侵

基准 `upstream/main@5f0108f5` 已不在本分支历史里（本分支与 upstream 的 merge-base 是
`cb698832`），因此下列数字按 `git diff upstream/main@5f0108f5...HEAD`（**三点**，即对
merge-base 求差）重算，复算时间 2026-08-19：**311 个文件变更，其中 220 个是新增文件、
198 个路径里带 `ansich`**（独立包 `backend/packages/ansich/`、适配层 `deerflow/ansich/`、
迁移 0005–0025、Gateway 路由、前端页面、测试、`ansich/docs/`）。

落到主仓库**既有后端生产代码**上的是 **45 个文件、+1940/−187 行**，另有 6 个新文件长在
既有生产目录里（`app/gateway/routers/ansich.py`、`app/gateway/feedback_evaluation.py`、
`deerflow/config/ansich_config.py`、`deerflow/runtime_descriptor.py`、
`deerflow/authz/outcome.py`、`deerflow/agents/middlewares/tool_transform_meta.py`）。改动形态
仍集中在三类：中间件链上挂只读探针、run worker 与 task 工具的生命周期挂钩、config/deps 装配。

一处诚实说明：本分支现在还带着与 Ansich 无关的工作（前端 trajectory 视图），所以上面的
**总数不能整个算到 Ansich 头上**；`frontend/src/` 里另有 7 个既有文件被修改
（+1367/−88），其中就含该视图，故不并入上面那 45 个文件的账。

依赖方向单向（`deerflow → ansich`，独立包不依赖 DeerFlow / LangGraph / FastAPI）；只写
`ansich_*` 表；由 startup-only 的 `ansich.enabled` 全局门控，关闭即完全旁路。

## 8. 实现状态

- **已实现**（本地纵向切片可运行）：Phase 1–10 —— Task 生命周期、Step/attempt/上下文快照、
  ToolCall 责任链、上下文谱系与压缩、活动任务/心跳/预算、失控告警与干预、AgentRelease 比较、
  子 Task 树与 inclusive usage、Scope/授权/副作用审计、评估输入与语义 quality Belief
  （`evaluation.recorded`、`evaluation-projector@1`、resolver `ansich-default@2`、
  cohort 可比性）。
- **Phase 11 前的加固批**（2026-08-19）：把「归属 Phase 11 前」的到期跟进项一次结清——
  wall_time 收敛为单一写者并改成 max 型高水位通道（迁移 `0024`）、scope-safety 按 watermark
  区间增量重估（持久表 `ansich_assessor_watermarks`，迁移 `0025`）、bash 首命令词产出
  `filesystem_delete`/`permission_change`（observed 侧只记 `inferred`，不改变
  `unverified_effect` 结论）、孤儿 `requested` operator action 的过期接管、externalized
  payload 的 None 守卫、settle 时序门禁，以及补齐 `?by=model` 用量聚合。
- **PostgreSQL 矩阵已首次执行**：opt-in 集成层（`make test-postgres`，`DEER_FLOW_TEST_POSTGRES_URL`
  开关）在真实 PostgreSQL 16.2 上跑通整条 26 个 revision 的迁移链（空库升 head、
  head↔`0004` 往返、二次升级幂等）、`bootstrap_schema` 三个分支（含 `pg_advisory_lock`）与
  一次端到端服务冒烟。
- **未标记最终完成**：后端全量套件在 PostgreSQL 上的对等运行与多 worker 并发语义（SQLite
  单写者下根本不成立的丢更新窗口只有它能证伪）、关闭 Ansich 的性能基准、生产 paper drill。
- **计划中**：Phase 11 生产韧性/重放/保留策略、Phase 12 验收演练。

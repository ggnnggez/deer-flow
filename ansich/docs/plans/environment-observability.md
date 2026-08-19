# 环境观测（OS 级信号）— Phase 10 之后、Phase 11 之前的独立切片

## 实现状态（2026-08-19）

已形成可运行的纵向切片：新增 `environment.sampled` Observation（subject 为 sandbox/host Scope），由两条采集路径产生——`AnsichEnvironmentProbe`（仿 `AnsichTaskHeartbeat`，AIO 容器读 cgroup、local 读宿主磁盘/PSI 并声明 host+sandbox 两个 Scope、其余 provider 只发一条 `uninstrumented` 声明）与 local bash 的按命令 `ProcessGroupSampler`（`deerflow/sandbox/telemetry.py`，ansich 无关，经 `asyncio.to_thread` 边界的显式 `Context` 回传，由既有 Ansich tool probe 链发射）。`environment-projector@1` 注册在 `task-safety` 之后，产出三张读模型（migration `0026_ansich_environment`：`ansich_environment_coverage`、`ansich_environment_state`、`ansich_tool_env_samples`）。`environment-pressure@1` 挂进现有周期 operations 评估循环，产出 `environment_pressure:<metric>` 与 `environment_leak:fd_open` 两类 transition-only Assertion，以及 `environment_pressure`/`environment_leak_suspected` 两个新 `AlertType`，Alert evidence 附 `possibly_affected_task_ids`（时间相关，非因果）。`GET /api/ansich/tasks/{task_id}/environment` 与 ToolCall 详情的 additive `environment_sample` 字段是读侧接口；前端 Task 详情“运行环境”面板落地。

本地验收覆盖 SQLite 迁移/重放、后端 Ansich 回归与前端 lint/typecheck/单元测试；真实 PostgreSQL 升级矩阵、关闭 Ansich 的性能基准和生产 paper drill 仍是与其余 Phase 共同的最终生产就绪门禁（见 [README.md](README.md) 的 PostgreSQL 门禁进度条目）。

## 1. 定位与来源

本切片不是 Phase 11 的一部分，也不占用 Phase 编号——它是 concepts.md 第 9 条同步规则驱动的独立纵向切片，插在 Phase 10（评估与语义 Belief）完成、Phase 11（生产韧性、重放与保留策略）开工之前落地，因为环境观测的 `host` Scope 机制是 Phase 11 预留的 `observability_degradation`/`projection_failure` process-subject 映射要复用的基础设施（见 [ansich-design-document.md §4.9](../ansich-design-document.md) 与 [ansich-design-document.md §10.7](../ansich-design-document.md)）。

**必读来源**（本切片的每个决定都以它们为准）：

- 设计 spec：[`docs/superpowers/specs/2026-08-19-ansich-environment-observability-design.md`](../../../docs/superpowers/specs/2026-08-19-ansich-environment-observability-design.md) —— 概念/措辞的唯一来源；本文与 concepts.md 的新小节均逐条摘录自此文档，不新造术语。
- 实施计划：[`docs/superpowers/plans/2026-08-19-ansich-environment-observability.md`](../../../docs/superpowers/plans/2026-08-19-ansich-environment-observability.md) —— 12 个任务的逐任务实现细节、self-review 记录与验收标准。
- 执行记录：`.superpowers/sdd/2026-08-19-ansich-environment-observability/`（各任务 brief/report、批次 diff）。

## 2. 与 Phase 11 的关系

Phase 11（生产韧性、重放与保留策略）尚未开始实现。本切片先行交付的部分与 Phase 11 直接相关，实施 Phase 11 时必须覆盖：

- Phase 11 的 scope-subject 映射矩阵（决定哪些 process-subject Alert 挂在哪个 Scope 上）必须把本切片新增的 `host` Scope kind 和 `host_environment` relation role 一并纳入，不能只覆盖 Phase 11 自己新增的 subject 类型。
- Phase 11 的 retention 矩阵（哪些 Observation kind / 读模型可以被压缩或过期）必须覆盖 `environment.sampled` 的高频 continuous 样本（体量与 heartbeat 同数量级）与 `ansich_tool_env_samples`（每 `tool_call_id` 至多一行，天然有界，但随 ToolCall 保留策略一起过期）。
- `observability_degradation`/`projection_failure` 两个保留域值启用时，其 process-subject 应直接绑定本切片建立的 `host` Scope，而不是另建一个 host 级 Scope kind。

## 3. 测试矩阵落位

以下用例对应 spec §7 的测试矩阵，逐条落位到已实现的测试文件（均在 `backend/tests/`，路径相对 `backend/`）：

| 层 | 关键用例 | 落位 |
|---|---|---|
| contracts | kind/subject 校验；标记字段缺失即拒；`uninstrumented` 必须空 metrics | `tests/ansich/test_contracts_environment.py`、`tests/ansich/test_environment_models.py` |
| probe | 按 provider 分派；ownership 丢失即停；采样异常 fail-open；uninstrumented 只发一条；tick 经 `to_thread` 下放 | `tests/ansich/test_environment_probe.py`、`tests/blocking_io/test_environment_probe.py`（blocking-io 锚点） |
| local sampler | 真实子进程的进程组聚合（Linux）；短命令 `sample_count=0` 路径；sandbox 层零 ansich import | `tests/test_local_sandbox_telemetry.py`、`tests/ansich/test_env_samplers.py`、`tests/test_harness_boundary.py`（边界钉子） |
| projector | 幂等重放；现状行先锁后读；`consecutive_growth_count` 重放确定性 | `tests/ansich/test_environment_projector.py` |
| assessor | 仅类别跃迁追加断言；缺样本/未观测 → unknown 而非 ok；泄漏规则拒收 per_command 与 host_shared 输入；episode open→更新→resolve→复发编号 | `tests/ansich/test_environment_assessor.py`、`tests/ansich/test_environment_alerts.py` |
| API/DTO | task environment 读；unknown/coverage/environment_scope 全链路不丢；alert filter 放行新类型 | `tests/test_gateway_ansich_environment.py` |
| 前端 | 新组件单测 + 类型对齐 | `frontend/tests/unit/core/ansich/environment-presentation.test.ts`（组件：`frontend/src/components/workspace/ansich/environment-panel.tsx`） |

## 4. 已知边界（v1 明确不做）

- warm 空闲期采样（无 run 即无 task_id 可挂）；空闲期泄漏由下个 run 首 tick 的存量读数如实反映。
- subagent 独立环境观测（同一 sandbox Scope 采两遍是重复事实）。
- 外部 metrics 管道（Prometheus/OTel）：破坏 Observation 层重放链。
- per_command 数据产生 Alert：v1 严格只读侧展示，不接入 episode 状态机（spec §5.3）。

详见 spec §4.5、§5.3。

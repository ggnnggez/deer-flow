# 环境观测（OS 级信号）— Phase 10 之后、Phase 11 之前的独立切片

## 实现状态（2026-08-19）

已形成可运行的纵向切片：新增 `environment.sampled` Observation（subject 为 sandbox/host Scope），由两条采集路径产生——`AnsichEnvironmentProbe`（仿 `AnsichTaskHeartbeat`，AIO 容器读 cgroup、local 读宿主磁盘/PSI 并声明 host+sandbox 两个 Scope、其余 provider 只发一条 `uninstrumented` 声明）与 local bash 的按命令 `ProcessGroupSampler`（`deerflow/sandbox/telemetry.py`，ansich 无关，经 `asyncio.to_thread` 边界的显式 `Context` 回传，由既有 Ansich tool probe 链发射）。`environment-projector@1` 注册在 `task-safety` 之后，产出三张读模型（migration `0026_ansich_environment`：`ansich_environment_coverage`、`ansich_environment_state`、`ansich_tool_env_samples`）。`environment-pressure@1` 挂进现有周期 operations 评估循环，产出 `environment_pressure:<metric>` 与 `environment_leak:fd_open` 两类 transition-only Assertion，以及 `environment_pressure`/`environment_leak_suspected` 两个新 `AlertType`，**Alert 读模型行**附 `possibly_affected_task_ids`（非空覆盖语义；时间相关，非因果），evidence 仍是贡献样本的 obs 引用。`GET /api/ansich/tasks/{task_id}/environment` 与 ToolCall 详情的 additive `environment_sample` 字段是读侧接口；前端 Task 详情“运行环境”面板落地。

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
| 前端 | 新组件单测 + 类型对齐；sparkline 投影与断线规则 | `frontend/tests/unit/core/ansich/environment-presentation.test.ts`、`frontend/tests/unit/components/workspace/ansich/sparkline.test.ts`（组件：`frontend/src/components/workspace/ansich/environment-panel.tsx`、`.../sparkline.tsx`） |

## 4. 已知边界（v1 明确不做）

- warm 空闲期采样（无 run 即无 task_id 可挂）；空闲期泄漏由下个 run 首 tick 的存量读数如实反映。
- subagent 独立环境观测（同一 sandbox Scope 采两遍是重复事实）。
- 外部 metrics 管道（Prometheus/OTel）：破坏 Observation 层重放链。
- per_command 数据产生 Alert：v1 严格只读侧展示，不接入 episode 状态机（spec §5.3）。

详见 spec §4.5、§5.3。

## 5. 与 spec 的实现级偏差（有意，已声明）

前两条随实施计划一同论证（见 [实施计划「与 spec 的两处实现级偏差」](../../../docs/superpowers/plans/2026-08-19-ansich-environment-observability.md)），第三条在终审时补记：

1. **`possibly_affected_task_ids` 不进 assertion value，也不作为 alert evidence obs**：它随运行中 Task 集合变化，放进 `value_json` 会破坏「仅跃迁追加」去重。落点改为 **Alert 读模型行**的附加 JSON 列（reconcile 变更时按非空覆盖语义刷新），evidence 仍是贡献样本的 obs 引用。语义不变（「采样时正在运行」），存储位置从 evidence 挪到读模型。
2. **local 的连续 tick 同时声明两个 Scope**：host Scope（承载 host_shared 读数）与 sandbox Scope（`local:{thread_id}`，per_command 样本的 subject）。因为 per_command 观测需要 sandbox Scope 实体存在，而 local 的连续读数挂在 host Scope 上。
3. ~~**spec §6.2 的「ToolCall 行有样本时显示 io/fd 小字」v1 未实现**~~ **已解决（2026-08-19 后续批次）**：ToolCall 行现在渲染 fd 峰值与读/写字节的小字（`frontend/src/components/workspace/ansich/step-explorer.tsx` 的 `ToolCallEnvironmentLine`）。数据来源是下面新增的 **B2 task 级批量读** 而不是每行一次的 ToolCall 详情请求：一个 Step 面板可能同时渲染数十个 ToolCall，逐行详情请求会把一次面板渲染放大成数十次 HTTP 调用，而 task 级读天然有界（每 `tool_call_id` 至多一行）。因此 ToolCall 详情上的 additive `environment_sample` 字段保留为**单调用 API 读**（外部 API 消费者用），前端不再是它的消费者——这是本条的实现级取舍，不是字段被废弃。采样器没报的计数器留空而不是渲染 0。

## 6. 环境趋势读侧（2026-08-19 后续批次）

两个**惰性、有界、不轮询**的 admin-only 读接口，服务于面板的 sparkline 趋势曲线：

- `GET /api/ansich/scopes/{scope_id}/environment/history?environment_scope=&metric=&window_minutes=&max_points=`：单个 `(Scope, environment_scope, metric)` 的近期读数序列，按 `occurred_at` 升序。**不新建读模型**——直接重放不可变的 `environment.sampled` Observation，因为它唯一的消费者是一条曲线，为此再加第四张可重建表不划算。`environment_scope` 非三档之一即 422，`metric` 不符合 `^[a-z][a-z0-9_]{0,63}$` 即 422。**没报该 metric 的样本被跳过而不是记 0**（concepts 第 9 条第 6 款：缺失不是零），所以序列里的空档是真实空档，前端按「相邻间隔超过中位采样间隔 3 倍即断线」渲染，绝不插值。存活点超过 `max_points` 时保留**最新**的一段并置 `truncated=true`。
- `GET /api/ansich/tasks/{task_id}/environment/tool-samples`：该 Task 的逐命令样本序列（`ansich_tool_env_samples`，按 `started_at` 升序，上限 500 行，超出置 `truncated=true`）。前端用它渲染「逐命令」段的 fd 峰值 / 读写字节曲线（**横轴是命令执行顺序，不是时间轴**——这些样本各自描述一条命令自己的窗口，按时间戳排布会暗示一段从未做过的连续测量），以及 ToolCall 行的 io/fd 小字。

两者都走与同族读相同的 admin guard 与 503 降级路径；in-memory 后端与降级后端返回空视图而不抛错。

**已登记的后续项**：history 查询按 subject 过滤未建 (subject_id, kind, occurred_at) 索引 —— 环境观测体量与 heartbeat 同级故可接受，量级上升时补索引。



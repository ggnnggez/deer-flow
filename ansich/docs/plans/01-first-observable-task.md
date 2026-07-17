# Phase 1 — 第一条可观测 Task

## 0. 实施状态（2026-07-17）

当前代码已完成本阶段的主纵向链路：独立 `ansich-core`、嵌入式生命周期、严格且排除 secret-bearing field 的 Observation、producer sequence loss range、恢复后的 `observability.degraded`、`ansich_*` 物理表、原子 writer、可租约重试的异步 projector、Task/Scope/Relation/ControlBelief 投影、投影重建、管理员过滤/游标 API，以及 dev/op Operations/Task 页面。正常、失败、中断 Run 和 Ansich 存储失败的 fail-open 行为均有测试。

阶段暂未关闭，剩余验收项是：在真实 PostgreSQL 上执行迁移/FK/claim 并发矩阵；继续扩充 403、unknown/degraded 的浏览器覆盖（当前已覆盖管理员列表→详情与 503）；量化 `enabled=false` 相对基线的 Run 行为与开销；按 Phase 12 约定执行生产形态 paper drill。未完成这些项目之前不得开始依赖 Phase 1 生产就绪性的部署承诺。

## 1. 交付目标

本阶段建立最小但完整的纵向链路：Gateway 启动嵌入式 Ansich 服务；顶层 DeerFlow Run 产生 Task 生命周期 Observation；BatchWriter 原子写入 Observation 与 projection job；Projector 生成 Task、Transition 和 Current Belief；管理员能够通过 `/api/ansich/tasks` 和工作区页面看到结果。

本阶段结束后，系统必须能回答四个具体问题：某个 DeerFlow `run_id` 是否被观测、它当前处于什么控制状态、这个状态由哪些 Observation 支持、Ansich 自身是否丢失或积压了数据。

## 2. 范围与非目标

本阶段包含 Task、基础 Scope、控制 Belief、Collector、BatchWriter、单实例 Projector、Health、管理员 Task 列表/详情。暂不采集 Step、LLM 输入、ToolCall、预算、Alert 和 AgentRelease；这些字段在 API 中不得用占位假数据替代。

`ansich.enabled=false` 时不得构造后台线程、创建探针或改变 Run 路径。`ansich.enabled=true` 但数据库为 `memory` 或存储初始化失败时，Gateway 继续启动，Ansich 进入 `failed`/`degraded` 状态，Run 仍可执行。

## 3. 代码与依赖结构

新增独立包：

```text
backend/packages/ansich/
  pyproject.toml
  ansich/
    __init__.py
    contracts/observation.py
    contracts/belief.py
    contracts/health.py
    ids.py
    collector.py
    service.py
    projection/base.py
    projection/task.py
    ports/observation_store.py
    ports/task_query.py
```

DeerFlow 集成放在：

```text
backend/packages/harness/deerflow/ansich/
  config.py
  context.py
  lifecycle.py
  persistence/models.py
  persistence/repository.py
  persistence/writer.py
  projection/worker.py
  probes/task_control.py
  query/tasks.py
```

`backend/pyproject.toml` 的 uv workspace 增加 `packages/ansich`，`backend/packages/harness/pyproject.toml` 依赖 workspace 包，并更新 `uv.lock`。增加一个 AST/import 边界测试，遍历 `backend/packages/ansich/ansich/**/*.py`，禁止导入 `deerflow`、`app`、`fastapi`、`langgraph`。

## 4. 配置与生命周期

新增 `AnsichConfig` 并挂到 `AppConfig.ansich`：

```yaml
ansich:
  enabled: false
  queue_capacity: 10000
  batch_size: 100
  flush_interval_ms: 100
  terminal_flush_timeout_ms: 2000
  projector_poll_interval_ms: 250
  projector_lease_seconds: 30
  projector_max_attempts: 5
```

该配置决定进程内单例、队列和 worker 生命周期，必须加入 `reload_boundary.STARTUP_ONLY_FIELDS`。配置示例的描述必须明确：修改后需要重启；启用 Ansich 不会把运行保护从 DeerFlow 移走。

在 `app.gateway.deps.langgraph_runtime()` 初始化 SQL Engine/SessionFactory 之后构造 `AnsichService`，保存到 `app.state.ansich_service`。退出顺序固定为：拒绝新 Observation、停止 Task heartbeat（本阶段尚为空实现）、有界 drain Collector、停止领取 projection jobs、完成当前事务、释放服务；总耗时受 Gateway shutdown budget 约束。

## 5. Observation 契约与 ID

`ObservationEnvelopeV1` 使用 Pydantic strict model，至少包含：

```text
obs_id: UUID 字符串
schema_version: 1
kind: task.created | task.started | task.completed | task.failed |
      task.interrupted | observability.degraded
occurred_at: UTC aware datetime
recorded_at: UTC aware datetime
task_id: UUID 字符串
subject_type: "task"
subject_id: task_id
fidelity_class: "hard"
producer: {name, version, instance_id}
source_event_id: 非空字符串
correlation_id: run_id
causation_obs_id: 可空
payload: 小 JSON 或 payload_ref
```

Ansich 主键使用应用生成 UUID4，不使用 DeerFlow/provider ID。顶层 Task 对应 `run_id`，并在投影中以 `UNIQUE(source_kind, source_id)` 保证一个 Run 只对应一个 Task。probe 的 `source_event_id` 使用稳定组成，例如 `run:{run_id}:task:started`；终态使用 `run:{run_id}:task:terminal:{terminal_kind}`，同一生命周期信号重试会命中唯一约束。

Collector 内部使用有界 `deque`、`threading.Lock` 和 event-loop `call_soon_threadsafe` 唤醒 writer，使 async Run 和子线程均可调用非阻塞 `record()`. 队列满、验证失败或 loop 已关闭时只更新进程内 loss range/计数并返回 `RecordReceipt(accepted=False, reason=...)`，不得向 Agent 路径抛异常。

每个 producer instance 维护单调 `producer_seq`。队列溢出时记录 first/last lost sequence；存储恢复后写入 `observability.degraded`。如果无法确定范围，health 返回 `loss_detected=true` 和 `range_known=false`，不能伪造范围。

## 6. 第一批物理表

新增下一条 Alembic revision（当前仓库预期为 `0006_ansich_task_core`），模型进入 `deerflow.persistence.models` 的 import 集合，确保空库 `create_all + stamp head` 路径不会跳过 Ansich 表。

本阶段创建：

- `ansich_payloads`：`payload_id`、`content_type`、`encoding`、`compression`、`byte_size`、`sha256`、`body`、`created_at`。
- `ansich_observations`：SQLite 使用 exact `INTEGER` 自增 `ingest_seq`，PostgreSQL 使用等价 sequence/bigint；另有唯一 `obs_id`、协议字段、`producer_seq`、`payload_json`、`payload_ref_id`。
- `ansich_projection_jobs`：`job_id`、`obs_id`、`projector_name`、`projector_version`、`status`、`attempts`、`available_at`、`lease_owner`、`lease_expires_at`、`last_error`。
- `ansich_projection_errors` 和 `ansich_projector_versions`。
- `ansich_entities`、`ansich_tasks`、`ansich_scopes`、`ansich_relations`、`ansich_relation_evidence`。
- `ansich_belief_assertions`、`ansich_current_beliefs`、`ansich_transitions`、`ansich_belief_evidence`。
- `ansich_task_summaries`，作为列表查询 read model。

关键约束和索引：

```text
UNIQUE(producer_name, producer_instance_id, source_event_id)
UNIQUE(ansich_tasks.source_kind, ansich_tasks.source_id)
UNIQUE(ansich_current_beliefs.subject_id, field_name, resolver_name, resolver_version)
UNIQUE(ansich_projection_jobs.obs_id, projector_name, projector_version)
INDEX ansich_observations(task_id, ingest_seq)
INDEX ansich_observations(kind, occurred_at)
INDEX ansich_projection_jobs(status, available_at, lease_expires_at)
INDEX ansich_task_summaries(control_value, last_evidence_at)
```

`payload_ref_id` 和 inline payload 必须二选一。外键删除规则要显式写入 migration；不要依赖 SQLite 默认行为，测试连接必须确认 `PRAGMA foreign_keys=ON`。

## 7. 写入和投影事务

BatchWriter 每批在一个 SQLAlchemy transaction 中完成：payload upsert、Observation insert、每个已注册 projector 的 job insert。任一步失败则整批回滚；不得出现 Observation 已提交但没有 projection job 的状态。重复 Observation 的 insert 使用唯一键识别，查询已有 `obs_id` 后返回 deduplicated receipt，不重复创建 job。

Phase 1 projector 只有 `task-structural@1` 和 `task-control@1`：

1. `task.created` 创建 Entity/Task、owner/thread Scope 和 `within_scope` relation。
2. 生命周期 Observation 追加 hard Belief Assertion 与 Transition。
3. resolver `control-state@1` 按 `occurred_at`、有效状态机和 ingest sequence 决定 Current Belief；晚到旧事件可修复历史 Transition，但不能把较新的终态退回 running。
4. 更新 `ansich_task_summaries`，写入 control Belief 的完整元数据、last evidence、projection watermark 和 observability health。

所有 upsert 必须以 Observation 或稳定自然键为幂等依据。Projector 不读取当前 wall clock 推断 Task 状态。

## 8. DeerFlow Task 探针

扩展 `RunContext` 增加可空 `ansich_service` 和 `ansich_task_id`。在 Gateway 创建 `RunRecord` 后、调度 `run_agent()` 前分配 Task ID并记录 `task.created`；`run_agent()` 外层在实际开始执行时记录 `task.started`。终态只能从 `RunManager`/worker 最终结果产生，不能使用任意 LangChain nested `on_chain_end`。

异常映射必须区分：正常完成、Agent 异常失败、用户/系统 interrupt。若终态写入失败，Run 返回值保持原样；`flush_task(task_id)` 只等待位于 terminal barrier 之前的项目，超时记录 degradation 后返回。

owner user ID、thread ID、外部触发来源只进入 Scope/Observation；平台 token、cookie、Authorization header 和 DSN 不进入 payload。

## 9. API 与前端

新增 admin-only 路由，统一调用 `await require_admin_user(request)`：

```text
GET /api/ansich/tasks?control=&from=&to=&limit=&cursor=
GET /api/ansich/tasks/{task_id}
GET /api/ansich/tasks/{task_id}/timeline
GET /api/ansich/health
```

Task 的 control state DTO 必须是：

```json
{
  "value": "running",
  "as_of": "...",
  "asserted_at": "...",
  "source": {"name": "task-control", "version": "1"},
  "fidelity_class": "hard",
  "selected_by": {"name": "control-state", "version": "1"},
  "evidence_obs_ids": ["..."]
}
```

无证据时返回同结构且 `value="unknown"`，不能返回 `null` 或推测状态。所有响应附带 `projection_status={watermark, lag_ms, failed_jobs, lost_ranges}`。数据库不可用时 `/health` 仍从进程状态返回 200 和 `status=failed`；依赖数据库的 Task API 返回 503 加同一 health 摘要。

前端新增 `/workspace/ansich/operations` 和 `/workspace/ansich/tasks/[task_id]` 的最小页面。`frontend/src/core/ansich/api.ts` 负责 fetch 和错误类型，`queries.ts` 使用 TanStack Query；列表只显示 Task ID、source run、控制 Belief、最后证据、观测健康。不得在本阶段显示虚假的 Step 数或进度百分比。

## 10. TDD 与验证矩阵

先写以下失败测试：

- core contract：aware datetime、非法 kind、裸 state DTO、secret-field payload 被拒绝。
- collector：多线程 record、满队列、closed loop、producer sequence loss range、record 永不向调用方抛出。
- writer：原子回滚、重复 envelope 去重、payload/job 一致性。
- projector：正常状态机、重复事件、completed 先于 started 到达、旧 running 不覆盖 completed、重放两次结果相同。
- migration：SQLite/PostgreSQL 表、FK、unique/index 一致；空库 bootstrap 能直接看到 Ansich 表。
- worker integration：正常 Run、失败 Run、interrupt Run、terminal flush 超时、模拟数据库故障时 Run 仍成功。
- API：admin 通过、普通 user/匿名拒绝、unknown Belief 完整、DB down health 仍可读。
- frontend unit/E2E：列表、详情、unknown/degraded 展示、403/503、从列表导航详情。

后端运行 `cd backend && make test`、`make lint`、`make format`；前端运行 `pnpm test`、`pnpm check`，关键页面运行 `pnpm test:e2e`。

## 11. 完成条件

- 同一个 `run_id` 无论 probe 重试多少次，只产生一个 Task 和一组幂等 Transition。
- terminal Observation 落库失败或 flush 超时不会改变 DeerFlow Run 的 completed/failed/interrupted 结果。
- Task API 的每个状态都具有 Belief 元数据和证据。
- 关闭 Ansich 后基准 Run 的事件、输出和持久化行为与改动前一致。
- 删除全部 Phase 1 投影表并重放 Observation，可得到相同 Task read model。

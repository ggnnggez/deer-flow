# Ansich 环境观测(OS 级信号)设计

日期:2026-08-19
状态:已与维护者逐节确认的设计 spec,待实现计划(writing-plans)展开。

## 1. 背景与目标

Ansich 目前的全部证据来自 DeerFlow runtime 采集(决策、attempt、ToolCall、heartbeat、预算等)。
本设计引入第二类证据来源:**执行环境的 OS 级观测信号**(fd、io、内存、磁盘、压力),
使运维告警能够回答"Agent 运行所处的环境是否处于资源压力/退化状态",并让 Task 详情
能反查"它运行期间沙箱环境有没有活跃的环境告警"。

约束(全部沿用 ansich 既有纪律):

- 三层模型不变:环境样本是 Observation(事实),读模型可重建,判断是带版本的
  Assertion/Alert;任何读模型不得反向成为事实来源。
- fail-open:采集、投影、评估失败不得影响 DeerFlow 业务运行。
- correlation ≠ causality:环境信号与 Task 只有时间相关性时,措辞与建模都不得
  声称因果("possibly affected",同 `possible_exposure` 的措辞纪律)。
- `unknown` 是一等值:缺数据、无 instrumentation 都必须显式表达为 unknown/未观测,
  绝不用缺行或默认 ok 表达。
- 没有足够 instrumentation 就记录 coverage,不硬猜(同 Effect 的纪律)。

## 2. 范围决策(已确认)

1. **观测对象以沙箱执行环境为主**(v1),不做宿主机全局监控层;local sandbox 的
   宿主共享信号作为显式标记的 `host_shared` 形态纳入。
2. **v1 只做"环境自身的告警"(方案 1)**:Alert subject 是 sandbox/host Scope,
   不产生 Task 级 `environment.pressure` Belief;Task 侧通过读模型 join 反查
   环境告警。升级为 Task Belief 留待真实使用证据。
3. **local sandbox 必须有真实数据**,但严格显式标记语义等级,不冒充容器指标。

### 关键事实(设计依据,均为代码现状)

- Task ≠ thread:lead 的一次 Run 是 root Task,subagent 委派是 child Task;
  thread 是 Scope(`thread` kind),不是 Task。
- Sandbox 按 thread 分配(`local:{thread_id}` / AIO、Boxlite 以 `user_id:thread_id`
  确定性命名),经 warm pool 跨 run 存活,先后承载同一 thread 的许多 root Task;
  fd 泄漏等存量状态跨 Task 累积。
- 一个 sandbox 同时承载多个 Task 是常态(root + 并发 subagent 共享父 thread 的沙箱),
  fd/io 计数器天然是 sandbox 粒度,无法归属单个 Task —— 这是 Alert subject 定在
  sandbox Scope 的根本原因。
- 不同 provider 的"环境"物理形态不同:AIO 容器是长驻环境(存量有意义);local 每条
  bash 是短命子进程(无跨命令存量,能诚实测的是单命令进程组消耗 + 宿主共享信号);
  E2B/Boxlite 无现成 instrumentation。
- `ObservationEnvelope.task_id` 必填:环境采样永远记在"当时正在运行、其 probe 执行了
  采样的 root Task"名下;v1 只在 run 活跃期间采样,warm 空闲期是显式覆盖空洞。

## 3. 数据契约(Observation 层)

### 3.1 新 Observation kind:`environment.sampled`

- `subject_type = "scope"`,`subject_id` 为 sandbox Scope 或 host Scope 的 scope_id。
- `contracts.py::_validate_subject` 链新增校验:subject_type 必须是 `scope`,payload
  必须携带完整标记字段,缺一即拒收。
- envelope `fidelity_class` 依惯例恒为 `hard`(描述"采到了这条样本"这一事实);
  判断强度由 assessor 依据 payload 的 `environment_scope`/`coverage` 决定
  (与 evaluation 的 fidelity 分层同构)。

### 3.2 Payload 结构(强制字段)

```json
{
  "environment_scope": "container | process_group | host_shared",
  "coverage": "continuous | per_command | uninstrumented",
  "window": { "started_at": "...", "ended_at": "...", "sample_count": 0 },
  "provider": "aio | local | ...",
  "metrics": {
    "fd_open":        { "value": 0, "limit": null },
    "io_read_bytes":  { "value": 0 },
    "io_write_bytes": { "value": 0 },
    "rss_bytes":      { "value": null }
  },
  "tool_call_id": null
}
```

硬规则:

1. **`environment_scope` 决定语义等级**,全链路(投影、assessor、API、前端)不可丢失:
   - `container`:沙箱隔离环境的真实存量(仅 AIO 容器 cgroup/fd);
   - `process_group`:单条命令进程组的消耗快照 —— 测不到存量,fd 值是该命令峰值,
     不是"沙箱当前打开数";
   - `host_shared`:与宿主机所有进程共享的信号(磁盘余量、PSI),永远不冒充沙箱指标。
2. 缺失的 metric 维度不写零,直接不出现(沿用 usage 的"未报告 ≠ 0"纪律)。
3. `coverage = "uninstrumented"` 仅允许空 `metrics`、`sample_count = 0`,每 run 至多
   发一条声明(见 4.3)。
4. `tool_call_id` 仅 `per_command` 形态填写;不为单条命令新造 Entity。
5. 幂等:`source_event_id = "run:{run_id}:env:{scope_id}:{tick}"`(continuous)或
   `"tool:{tool_call_id}:env"`(per_command),与 heartbeat 同款。

### 3.3 Scope 扩展

- `safety.py::ScopeKind` 新增 `"host"`。
- host Scope 身份用 hostname 的 stable ref hash 规范化(不把敏感绝对路径/凭证当 ID);
  单机部署下是一个固定 Scope。
- sandbox Scope 与 `within_scope` 关系是 Phase 9 现状,零新增。
- 注:Phase 11 预留的 `observability_degradation`/`projection_failure` 的
  process-subject 映射应与本设计共享 `host` Scope 机制,不另造。

### 3.4 采样频率与体量

continuous 跟随 heartbeat 节拍(独立配置键,默认同 `heartbeat_interval_seconds`),
每活跃 run 每 tick 一条,体量与 heartbeat 同数量级;per_command 每条 bash 至多一条。
原始样本是重放依据;断言只在类别跃迁时追加(见 §5)。

## 4. 采集器(DeerFlow 适配层)

全部位于 `packages/harness/deerflow/ansich/`;`packages/ansich` 核心保持框架无关。

### 4.1 连续 probe:`AnsichEnvironmentProbe`

新文件 `deerflow/ansich/probes/environment.py`,完全仿照 `AnsichTaskHeartbeat`:
`runtime/runs/worker.py` 在 `task.started` 后与 heartbeat 并排启动,每 tick 检查
run ownership,fail-open,terminal 观测前停止。tick 按 provider 分派:

- **AIO(container)**:读容器指标,发 `container/continuous` 观测,subject 为该
  thread 的 sandbox Scope。
- **Local**:tick 采宿主信号 —— workspace 所在文件系统磁盘余量
  (`shutil.disk_usage`)、PSI(`/proc/pressure/{io,memory}`,内核无 PSI 则省略该
  维度)—— 发 `host_shared/continuous` 观测,subject 为 host Scope。
- 每次采样经 `asyncio.to_thread` 下放(`/proc`、docker 读取是阻塞 IO,必须过
  blocking-io 门禁)。

只有 root Task 的 probe 采样;child Task 不重复发环境观测(同一 sandbox Scope 采两遍
是重复事实,child 经 `within_scope` 关系天然可反查)。

### 4.2 按命令采样:local 进程组 sampler

- `LocalSandbox._run_posix_command` 增加 **ansich 无关的**轻量 sampler:命令运行期间
  后台线程每 ~1s 枚举 `/proc` 中 pgid 匹配成员,累计 io 字节、记录 fd 峰值;命令结束
  时结果作为纯数据(小 dataclass)挂在执行结果上。sandbox 层不 import ansich。
- 发观测的是现有 Ansich tool probe 链(raw 执行探针),读到遥测后发
  `process_group/per_command` 观测,携带权威 `tool_call_id`。
- 短于采样间隔的命令允许 `sample_count = 0` + 仅终态读数,窗口字段如实记录。
- Windows local 沙箱无 `/proc`:不采,落入 4.3 声明。

### 4.3 覆盖声明:`coverage = uninstrumented`

E2B/Boxlite/Windows-local 等无采集能力的形态,probe 在 run 启动时发**一条**声明观测
(非每 tick)。读模型据此区分"环境未被观测"与"没出问题"。

### 4.4 配置(`config.yaml -> ansich`,startup-only)

- `environment_probe_enabled`(默认 `true`;fail-open + 体量与 heartbeat 同级)
- `environment_sample_interval_seconds`(默认跟 `heartbeat_interval_seconds`)
- `environment_per_command_sampling`(默认 `true`,仅影响 local)

### 4.5 明确不做(YAGNI)

- warm 空闲期采样(无 run 即无 task_id 可挂;空闲期泄漏由下个 run 首 tick 的存量读数
  如实反映)。
- subagent 独立环境观测。
- 外部 metrics 管道(Prometheus/OTel):破坏 Observation 层重放链,已排除。

## 5. 投影、assessor 与 Alert

### 5.1 投影:`environment-projector@1`

注册进现有 leased projector loop(幂等、可重放、可重建)。migration
`0026_ansich_environment`,两张可删除 typed 读模型:

1. `ansich_environment_state` —— 每 `(scope_id, environment_scope, metric)` 一行的
   **现状行**(拒绝每 tick 一行,吸取 wall_time 高水位教训):`latest_value`、`limit`、
   `as_of`、`window_started_at`、`sample_count`、`coverage`,以及趋势服务字段
   `consecutive_growth_count`(按 watermark 顺序重放可确定性重建)与
   `window_min_value`。读-改-写,照抄 `_upsert_high_water_contribution` 的
   **先锁后读**纪律。
2. `ansich_tool_env_samples` —— 每 `tool_call_id` 至多一行(per_command),供
   ToolCall 详情读,天然有界。

`uninstrumented` 声明投影为 state 行的 coverage 标记,不产生 metric 行。

### 5.2 Assessor:`environment-pressure@1`

挂进现有周期 operations 评估循环(与 heartbeat/dwell/budget 同节拍,只扫活跃 run
关联的 scope)。产出两类,严格分开:

**Assertion(Belief)**:对 Scope subject 断言 `environment.pressure.<metric>` 的类别
状态 `ok | warning | critical | unknown`,authority = `configured_rule`,带阈值
config hash 与贡献样本 obs 引用。只在类别跃迁时追加;数值留在读模型动态展示。
`unknown` 触发条件:run 活跃但超过 3× 采样间隔无样本(probe 故障/collector 丢失),
或 coverage = uninstrumented —— **缺数据永远是 unknown,不是 ok**。环境评估绝不写
Task 控制状态。

**AlertCondition**(进现有 episode 状态机;`AlertType` Literal 扩两个值并加入公共
filter 白名单):

- `environment_pressure` —— 存量/比率越阈。v1 规则:
  - container:`fd_open / limit`(warn 0.8 / crit 0.95);
  - host:磁盘余量、PSI 越阈(subject 为 host Scope,evidence 保留
    `environment_scope = host_shared`,前端必须展示为"宿主共享信号")。
  - `stable_condition_key = "env:{metric}"`;条件持续更新当前 episode,消失 resolve,
    复发编号 —— 全部复用现有机制。
- `environment_leak_suspected` —— **仅 container + continuous**:fd 连续增长 ≥ M 个
  样本、跨度 ≥ W 秒、净增 ≥ N(阈值进配置并入 rule config hash;默认 M=6、W=60、
  N=50,即约一分钟内净增 50 个 fd 且逐样本单调不降)。"suspected" 即断言
  强度:配置规则推断,非实证泄漏。**per_command 数据永远不喂此规则**(进程组快照测
  不到存量 —— environment_scope 语义分级的强制执行点)。

**Task 关联(方案 1 的反查)**:Alert evidence 附采样时刻该 scope 内 `running` 的
Task 列表,字段名 `possibly_affected_task_ids` —— 时间相关,不是因果。

### 5.3 per_command 的克制

v1 不从单命令样本产生任何 Alert:episode 状态机建模持续 condition,单命令尖峰是点
事件,硬塞会产生秒开秒关的 episode 噪音。其价值在读侧(ToolCall 详情、Task 时间线)。
点事件告警通道待真实使用证据后另行设计。

### 5.4 失效路径

probe/投影失败走现有 failed job → health degraded → operator retry,不回滚业务;
评估缺数据只产 unknown 断言。

## 6. 读侧 API 与前端

### 6.1 Gateway API(admin-only,现有 `/api/ansich` 路由)

- `GET /tasks/{task_id}/environment`:沿 `within_scope` 找 sandbox/host Scope,返回
  每 scope 的环境现状行(metrics + coverage + environment_scope)、当前
  `environment.pressure.*` Belief(unknown 完整下发,source/authority/evidence 不丢)、
  以及这些 scope 上活跃/历史环境 Alert episode 摘要。
- Alert 面零新路由:两个新 `AlertType` 进公共 filter,list/detail/acknowledge/dismiss
  复用;`possibly_affected_task_ids` 随现有 evidence 结构下发。
- ToolCall 详情读模型加 additive 可空字段 `environment_sample`(老前端忽略,契约不
  升版)。

### 6.2 前端(`/workspace/ansich`)

- Task 详情页"运行环境"面板:每 scope 一张卡,`environment_scope` 徽标显眼
  (容器实测 / 进程组快照 / 宿主共享)+ coverage 徽标(含"未观测"态);unknown 渲染
  为明确"未知",不用空白或绿色。
- Alert 列表接入两个新类型;detail 页 possibly-affected Tasks 措辞用"采样时正在运行"。
- ToolCall 行有样本时显示 io/fd 小字。

## 7. 测试矩阵

| 层 | 关键用例 |
|---|---|
| contracts | kind/subject 校验;标记字段缺失即拒;`uninstrumented` 必须空 metrics |
| probe | 按 provider 分派;ownership 丢失即停;采样异常 fail-open;uninstrumented 只发一条;tick 经 `to_thread` 下放(`tests/blocking_io/` 锚点) |
| local sampler | 真实子进程的进程组聚合(Linux);短命令 `sample_count=0` 路径;Windows 跳过;sandbox 层零 ansich import(`test_harness_boundary` 覆盖) |
| projector | 幂等重放;现状行先锁后读;`consecutive_growth_count` 重放确定性;进现有 rebuild/replay 矩阵 |
| assessor | 仅类别跃迁追加断言;缺样本/未观测 → unknown 而非 ok;泄漏规则拒收 per_command 与 host_shared 输入;episode open→更新→resolve→复发编号 |
| API/DTO | task environment 读;unknown/coverage/environment_scope 全链路不丢;alert filter 放行新类型 |
| 前端 | 新组件单测 + 类型对齐(`frontend/tests/unit/core/ansich`) |

## 8. 文档同步(concepts.md 第 9 条,同一 change set)

1. `ansich/docs/concepts.md` 新增"环境观测"小节(定义、边界、与 Scope/Alert 的关系);
2. `ansich/docs/ansich-design-document.md` 世界模型;
3. 独立的 environment-observability Phase 计划(不塞进 Phase 11,但注明与 Phase 11
   的 process-subject 映射共享 `host` Scope 机制)+ 本测试矩阵;
4. `contracts.py` 的 kind/payload 契约;
5. migration `0026_ansich_environment` + SQL typed projection + replay 测试;
6. API DTO 与前端类型,确保 unknown、coverage、environment_scope 传输不丢。

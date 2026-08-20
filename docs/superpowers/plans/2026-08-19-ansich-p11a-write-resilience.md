# Ansich P11-A 采集与写入韧性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Ansich 采集/写入侧从「DB 一次异常 = 整批永久丢失、无重试、无毒信隔离」加固为 spec §2 要求的生产形态:进程状态机、per-producer 账目、有界指数退避、毒信按条隔离、collector-sequence 界定的终端屏障、以及 F10-7 的 per-observation 持久化终态。

**Architecture:** 全部改动落在 `AnsichService`(`backend/packages/ansich/ansich/service.py`,框架无关包)与契约层(`contracts.py`),不新建 BatchWriter 类(裁决 RA1)。写路径新增:writer 在飞缓冲 + 有界退避重试 + 批失败后二分到逐条以隔离毒信;`flush_task` 从「按 task 抽取」改为「按 collector sequence 界定」;丢失观测进入有界 `obs_id` 追踪集,使评估回执能区分「丢失」与「排队中」。健康面新增 lifecycle 状态、producer 账目与 writer 块(全部 additive)。**本批零迁移**(0027 留给 P11-B)。

**Tech Stack:** Python 3.12 / Pydantic / SQLAlchemy async / pytest;前端 TypeScript(仅类型镜像与展示同步)。

**Spec:** `ansich/docs/plans/11-resilience-replay-and-retention.md` §2(执行者必读;§3/§4/§9 归 P11-B,勿越界)。现状事实以 recon 档案为准:`/tmp/claude-1000/-home-nan-c-project-deer-flow/3783b205-4932-4864-a312-47c88df09488/scratchpad/p11a-recon-dossier.md`(§1、§3、§5、§8、surprises 1-10/18/20;行号锚点全部对 HEAD `246964e5` 核实过,followup 注册表里的旧行号作废)。

## Global Constraints

- `backend/packages/ansich/` 禁止 import `deerflow`/`app`/FastAPI/LangGraph(钳制:`tests/ansich/test_contracts.py::test_ansich_core_has_no_deerflow_or_web_framework_imports`)。
- 采集永远 fail-open:任何本批新增机制的失败只 log,不影响 DeerFlow Run;`record()` 不可阻塞(仍在 `threading.Lock` 下,禁止在锁内做 IO/await)。
- 事件循环禁止阻塞 IO;退避等待只允许发生在 writer loop 协程内,绝不占 Agent 调用栈(spec §2 原文)。
- 缺数据永远是 `unknown`,不是 0/`ok`;丢失范围与账目只能多报不能少报。
- **本批不改投影/评估/lease 侧**(`sql.py` 的 claim/complete/error 路径、水位、Alert 全部是 P11-B 的);`persist_and_project` 的内部事务形状不动(批内原子性已成立,档案 §1.6)。
- **零迁移、零 ORM 变更**;迁移头保持 `0026_ansich_environment`,16 处 head-pin 一个都不许动。
- 契约变更只允许 additive(`FlushResult`/`AnsichHealth` 现有字段与语义不变;新增字段带默认值)。现有消费者:`FlushResult.reason` 被 `service.py:304/321/327`、`worker.py:462`、`probes/task_control.py:175`、评估回执逻辑 `service.py:373-441` 读取。
- 后端测试:`cd backend && PYTHONPATH=. uv run pytest tests/<file> -v`;全量 `uv run pytest tests/ansich -q` + `tests/test_persistence_bootstrap.py`;格式**只用** `uv run ruff format` / `uv run ruff check`(绝不 `uvx ruff`/`make format`)。前端:`cd frontend && pnpm check && pnpm test`。
- flake 协议:settle 家族测试翻红先单跑复核,两个结果都报告并抓失败文本。
- 新配置键全部进 `AnsichConfig`(`backend/packages/harness/deerflow/config/ansich_config.py`),按档案 §8 的三处线程路径接线(`create_embedded_ansich_service`、`create_sql_ansich_service`、`AnsichService.__init__`),描述带 `startup-only:` 前缀(现有字段欠此前缀,新字段不欠)。

## 裁决(不变量 + 错误代价;结构留给实现者,偏离须在报告里论证)

- **RA1 不抽 BatchWriter 类。** 不变量:写路径语义(下列各条)全部落在 `AnsichService` 现有方法族内,公共 API 不因重构而变。为什么:spec 的 "BatchWriter" 是概念不是类;抽类是 A1(obs layer)批的活,这里抽了 A1 就要再动一次。代价若错:A1 批多一次机械搬移。
- **RA2 lifecycle 状态 = 受法定迁移集约束的纯推导。** 不变量:①状态只能是 `starting|healthy|degraded|recovering|failed|shutting_down|stopped`;②运行中存在活跃事故(连续写失败>0 或 storage 不可用)时绝不显示 `healthy`;③`stop()` 进入后绝不显示 `healthy/degraded/recovering`;④可达迁移集恰为 spec §2 的图,测试逐条枚举钳制。实现为从可观测计数推导的纯函数(而非易漂移的状态字段),推导结果约束在法定迁移集内。语义:`starting`=start() 完成前;`degraded`=连续写失败>0 或 dropped/failed_jobs 活跃;`recovering`=失败清零但事故遗留积压未清(队列深度>batch_size 或未上报丢失范围非空);`failed`=`unavailable_reason` 非空;`shutting_down`/`stopped` 按 stop() 阶段。代价若错:管理 UI 标签失真一档,无数据风险。
- **RA3 per-producer 账目有界。** 不变量:①按 `(producer_name, producer_instance_id)` 记 accepted/dropped 计数、最后接受序号、serialization_failures、last_successful_flush_at;②map 有界(上限 256,LRU 淘汰),淘汰只能发生在新 producer 到来时且要计入一个 `evicted_producer_count`——绝不静默;③健康面新增 additive `producers` 列表(排序稳定)。代价若错:病态 instance_id 撑爆内存(有界防住)或账目对不上(计数器审计防住)。
- **RA4 退避重试属于 writer loop,批重试穷尽后二分隔离毒信。** 不变量:①任何 DB 异常不再立即丢批:先整批退避重试(指数,`writer_backoff_initial_ms=100` 起,`writer_backoff_max_ms=5000` 封顶,`writer_retry_max_attempts=5`);②穷尽后降级为逐条持久化,单条再失败 `writer_item_max_attempts=2` 次后该条判毒信:记 loss(reason=`poison_observation`)+ WARNING,**其余条继续**;③退避等待期间 `record()` 照常入队直到容量尾丢(现状语义);④在飞缓冲里的条目不重复计入 queue_depth,但健康面可见(writer 块);⑤不做异常类型白名单分类——「先重试、再隔离」对 transient/permanent 一视同仁,分类交给行为而非猜异常。代价若错:真毒信多挨 5 次重试(有界浪费);真瞬断被误判毒信的窗口=连续 5+2 次失败仍瞬断,概率极低且只丢单条并如实记账。
- **RA5 `flush_task` 屏障以 collector sequence 为界。** 不变量:①屏障语义 = 「持久化到本 Task 在调用时刻的最高队内序号 S 为止的**所有**队内条目(保序)」,而非今天的按 task 抽取(抽取本身就是 spec 禁止的不可解释重排,档案 surprise 4);②超时不再把未持久化条目判死:**退回队首**(保序),`FlushResult` 报 `timed_out=True` + `persisted_through`=最高连续已持久化序号——比今天的「超时即永久丢」更不丢数据,spec 未禁止;③投影 settle 等待保留现状(预算语义不变)。additive 字段:`persisted_through: int | None = None`、`lost_ranges: tuple[LostRange, ...] = ()`(仅本次屏障内实际损失)、`timed_out: bool = False`;现有三字段语义不变。代价若错:终端屏障可能顺带持久化了别的 Task 的更早条目(这本来就该发生)。
- **RA6 F10-7 回执终态 = 「不在 DB、不在队列、不在在飞」⇒ 丢失。** 不变量:①`record()` 已接受的 obs_id 若被记入丢失,进入有界追踪集(上限 4096,FIFO 淘汰);②评估回执状态解析新增终态判定:obs 不在追踪集也可由「DB 无此 obs 且不在队列/在飞」推得丢失(覆盖重启后场景);③丢失回执报 `failed`,绝不 `pending`;④判定绝不把「还在排队/在飞」判成丢失。代价若错:回执早报 failed(调用方重试,幂等键兜底)或晚报(现状,只会更好不会更坏)。
- **RA7 `stop()` 的排空有界。** 不变量:①stop 进入后 writer 对剩余队列的持久化尝试总预算 = 新键 `stop_drain_timeout_ms`(默认 10_000),期间不做退避等待(直试);②预算耗尽的剩余条目记 loss + 一条 WARNING,`stop()` 保证返回;③projector 侧排空行为本批不动(§8 归 C 批)。代价若错:关停时最多多等 10s 或多丢一段**已如实记账**的范围。
- **RA8 顺手修的两个账目诚实缺陷(同层、小):** ①`_record_observation_loss` 用 `producer_seq` 记范围而接受路径用 collector 序号(档案 §1.5)——统一为 collector 序号(`_flush_batch` 的 selected 元组本就携带);②`_reported_lost_range_count` 越过 `task_id is None` 的范围仍前进(把从未写入的标成已上报,档案 surprise 10)——改为把未上报的进程级范围留在显式的 `unreported process-wide ranges` 桶里,**本批不持久化它们**(subject 设计归 P11-B 的 host-Scope 工作),但账目不许再撒谎。代价若错:无——两处都是把假账改真账。
- **RA9 本批零迁移。** 一切状态在内存或 additive 契约字段;若实现中发现必须持久化的状态,STOP 上报而不是加表。
- **RA10 前端同步是收尾任务不是伴随任务。** 后端契约定稿后一次性同步 types.ts 镜像、presentation attention 映射(新 lifecycle 值:`starting`/`shutting_down` 不触发 attention,`recovering` 触发;沿用刚落地的分级横幅纯函数层)、健康抽屉的 writer/producer 展示、zh+en 文案。代价若错:一次前端返工。

---

### Task 1: 契约层 — lifecycle Literal、ProducerHealth、writer 块、FlushResult additive 字段

**Files:**
- Modify: `backend/packages/ansich/ansich/contracts.py`(`AnsichHealth` :655-681、`FlushResult` :637-642、`LostRange` :645-652 不动)
- Test: `backend/tests/ansich/test_contracts_resilience.py`(新建)

**Interfaces(后续任务全部依赖,值逐字用):**
- `AnsichHealth.status: Literal["starting","healthy","degraded","recovering","failed","shutting_down","stopped"]`(扩 3 值,序不重要)
- 新模型 `ProducerHealth(frozen)`:`producer_name: str`、`producer_instance_id: str`、`accepted_count: int`、`dropped_count: int`、`last_accepted_sequence: int | None`、`serialization_failures: int`、`last_successful_flush_at: datetime | None`
- 新模型 `WriterHealth(frozen)`:`consecutive_failures: int = 0`、`backoff_until: datetime | None = None`、`in_flight_count: int = 0`、`poison_observation_count: int = 0`
- `AnsichHealth` 新增(全 additive 带默认):`producers: tuple[ProducerHealth, ...] = ()`、`writer: WriterHealth = WriterHealth()`、`evicted_producer_count: int = 0`、`unreported_global_lost_range_count: int = 0`
- `FlushResult` 新增:`persisted_through: int | None = None`、`lost_ranges: tuple[LostRange, ...] = ()`、`timed_out: bool = False`

- [ ] Step 1: 失败测试——新 Literal 值可构造、旧值不回归;`ProducerHealth`/`WriterHealth` 字段与默认;`FlushResult` 三新字段默认值使旧构造调用(`FlushResult(persisted=True, processed_count=3)`)原样可用;`AnsichHealth` 旧构造调用不带新字段仍可用(additive 兼容钳)。
- [ ] Step 2: 跑红 → 实现 → 跑绿。
- [ ] Step 3: 全量 `tests/ansich` 确认零破坏(现有构造点都不带新字段)。Commit `feat(ansich): additive resilience contracts — lifecycle states, producer/writer health, flush barrier fields`。

### Task 2: lifecycle 纯推导 + 法定迁移集钳制

**Files:**
- Create: `backend/packages/ansich/ansich/lifecycle.py`
- Modify: `backend/packages/ansich/ansich/service.py`(`get_health` :256-287 的 status 内联表达式 :261 替换;stop 阶段打点)
- Test: `backend/tests/ansich/test_lifecycle.py`(新建)

**Interfaces:**
- `lifecycle.derive_status(LifecycleInputs) -> str`,`LifecycleInputs(frozen)`:`started: bool`、`stopping: bool`、`stopped: bool`、`unavailable_reason: str | None`、`consecutive_write_failures: int`、`dropped_count: int`、`failed_jobs: int`、`queue_depth: int`、`batch_size: int`、`unreported_loss_pending: bool`
- `lifecycle.LEGAL_TRANSITIONS: frozenset[tuple[str, str]]`(spec §2 的图逐边枚举)

推导规则(RA2 语义,写进 docstring):`stopped`(stopped)→`shutting_down`(stopping)→`starting`(not started)→`failed`(unavailable_reason)→`degraded`(consecutive_write_failures>0 or dropped_count>0 or failed_jobs>0)→`recovering`(无活跃失败但 queue_depth>batch_size 或 unreported_loss_pending)→`healthy`。注意:现状 `dropped_count>0` 永久判 degraded 的语义**保持**(丢失是事实不是瞬态;spec 的 recovering 只覆盖写失败恢复路径)。

- [ ] Step 1: 失败测试——每条推导规则一个用例;**迁移集钳**:对输入空间做代表性序列(start→写失败→恢复→积压清空→stop),断言相邻状态对 ∈ `LEGAL_TRANSITIONS`,且 `LEGAL_TRANSITIONS` 与 spec §2 图逐边相等(hardcode 期望集)。
- [ ] Step 2: 红→实现→绿;`get_health` 接线(`consecutive_write_failures` 等字段本任务先以 0/现有计数占位,Task 4 接真值)。
- [ ] Step 3: 全量 ansich 套件——现有断言 `status == "healthy"/"degraded"` 的测试不得翻红(推导对旧输入必须给旧答案)。**唯一豁免**:start() 之前旧表达式给 `stopped`、RA2 语义给 `starting`——若有测试钉了 pre-start 的 `stopped`,按新语义更新该测试并在报告里列出。Commit。

### Task 3: per-producer 账目(有界 LRU)+ 健康暴露

**Files:**
- Modify: `backend/packages/ansich/ansich/service.py`(`record_batch` :170-254 的 accept/reject 路径、`_persist_items` 成功路径、`get_health`)
- Test: `backend/tests/ansich/test_producer_accounting.py`(新建)

要点:计数更新全部在已持有的 `self._lock` 内(纯 dict 操作,无 IO);`_serialized_observation_size` 返回 -1 的条目计入该 producer 的 `serialization_failures`(档案 §1.4 第 1 步);flush 成功后为本批涉及的 producer 更新 `last_successful_flush_at`(writer 协程里,注意跨锁传递本批 producer 集);LRU 上限 256,淘汰计 `evicted_producer_count`(RA3)。

- [ ] Step 1: 失败测试——接受/拒绝各自计入正确 producer;序列化失败计数;flush 成功刷新时间戳;第 257 个 producer 触发淘汰且 evicted 计数+1;`get_health().producers` 排序稳定(按 name,instance)。
- [ ] Step 2: 红→实现→绿;全量。Commit。

### Task 4: writer 有界退避重试 + 在飞缓冲 + lifecycle 接真值

**Files:**
- Modify: `backend/packages/ansich/ansich/service.py`(`_writer_loop` :1237-1250、`_flush_batch` :1287-1292、`_persist_items` :1294-1308)
- Modify: `backend/packages/harness/deerflow/config/ansich_config.py` + `backend/packages/harness/deerflow/ansich/__init__.py`(三处接线,档案 §8)
- Test: `backend/tests/ansich/test_writer_retry.py`(新建)

**Interfaces:**
- `AnsichConfig` 新键(全 `startup-only:` 描述):`writer_retry_max_attempts: int = 5 (ge=1)`、`writer_backoff_initial_ms: int = 100 (ge=1)`、`writer_backoff_max_ms: int = 5000 (ge=1)`、`writer_item_max_attempts: int = 2 (ge=1)`、`stop_drain_timeout_ms: int = 10000 (ge=1)`(Task 7 用,一次加齐)
- **裁决 PA6(修正 RA2 的 recovering 语义,在本任务落地)**:`recovering` 必须有**事故证据**——`consecutive_write_failures == 0` 且(`unreported_loss_pending` 或 writer 重试在飞积压非空);T2 暂行的裸 `queue_depth > batch_size` 子句**删除**(正常负载突发会把健康系统标成恢复中,并造出 spec 图外的 healthy→recovering 边)。`LifecycleInputs` 以 additive 默认字段扩展(如 `writer_retry_backlog: bool = False`),T2 的既有测试保持绿;迁移集钳测试补「healthy 永不直达 recovering」的负向序列。
- 语义:`_persist_items` 失败不再立即记丢;批进入在飞缓冲,writer 按指数退避重试(等待用 `asyncio.wait()` 于 wake_event 与计时之间,**stop 信号可打断退避**);重试期间新批不越过在飞批(保序);成功后 `consecutive_failures` 清零。退避与失败计数暴露进 `WriterHealth`。

- [ ] Step 1: 失败测试(fake backend 可编程抛错):①瞬断两次后恢复→零丢失、全部落库、`consecutive_failures` 曾>0 终归 0、状态曾 `degraded` 终回 `healthy`(经 `recovering` 桥接的序列断言用 Task 2 的迁移集);②退避间隔逐次翻倍且封顶(用可注入时钟/monotonic 捕获,不真睡);③退避期间 record() 入队直至容量尾丢(计入丢失,writer 在飞批不算 queue_depth);④持续失败达 `writer_retry_max_attempts` 后进入 Task 5 的逐条路径(本任务先断言「批不再被整批判丢」,逐条行为 Task 5 钳)。
- [ ] Step 2: 红→实现→绿。**注意 `_projection_lock`/`persist_lock` 语义不变**;退避等待不持有任何锁。
- [ ] Step 3: 全量 ansich + bootstrap。settle 家族若翻红按 flake 协议处理。Commit。

### Task 5: 毒信隔离 — 批穷尽后二分到逐条

**Files:**
- Modify: `backend/packages/ansich/ansich/service.py`
- Test: `backend/tests/ansich/test_poison_isolation.py`(新建)

语义(RA4②):批重试穷尽 → 逐条 `persist_and_project([obs])`;单条失败重试至 `writer_item_max_attempts`,仍失败判毒信:以 collector 序号记 loss(reason=`poison_observation`;**RA8① 的序号统一在本任务落地**——`_record_observation_loss` 改用 selected 元组携带的 collector 序号,不再用 `producer_seq`)、`WriterHealth.poison_observation_count += 1`、WARNING(复用 `_warn_batch_loss` 的事件格式,`reason="poison_observation"`);**其余条继续且成功落库**。逐条阶段整体仍受 stop 排空预算约束(Task 7)。

- [ ] Step 1: 失败测试:①100 条中 1 条毒信(fake backend 对特定 obs_id 恒抛)→ 99 条落库、毒信记丢、计数+1、WARNING 断言(caplog);②毒信恰在批首/批尾的边界各一例;③两条毒信混布→98 条存活;④瞬断恰在逐条阶段消失→该条最终落库不判毒(item 重试语义)。
- [ ] Step 2: 红→实现→绿;全量。Commit。

### Task 6: `flush_task` sequence 屏障 + FlushResult 新字段接线 + RA8 账目修正

**Files:**
- Modify: `backend/packages/ansich/ansich/service.py`(`flush_task` :301-327、`_take_task_items` :1222-1235 重写、`_record_observation_loss` :1214-1220、`_report_degradation_if_storage_recovered` :1334-1370)
- Test: `backend/tests/ansich/test_flush_barrier.py`(新建)+ 触碰 `tests/ansich/` 中现有 flush_task 断言的最小修正

要点:屏障取「seq ≤ S 的全部队内条目」(S=本 task 最高队内序号;task 无队内条目→立即返回,`persisted_through` = 已知最高持久化序号或 None);超时未持久化条目**退回队首保序**(RA5②);`lost_ranges` 只含本次屏障内的实际损失(毒信);`persisted_through` = 最高**连续**已持久化 collector 序号(writer 需维护该水位——注意毒信造成的洞:洞前为界)。RA8②(进程级范围不再假上报:分桶 `_unreported_global_ranges`,健康面 `unreported_global_lost_range_count` 暴露,`_report_degradation_if_storage_recovered` 只对 task 范围推进已上报计数)在此任务落;RA8① 已由 Task 5 完成,本任务只消费其序号语义。

- [ ] Step 1: 失败测试:①A/B 两 task 交错入队,flush_task(A) 把 B 的更早条目一并持久化、B 的更晚条目留队;②超时(fake backend 挂起)→ 条目退回队首、`timed_out=True`、后续 writer 恢复后照常落库(**零丢失**,对照今天的丢弃语义);③`persisted_through` 在毒信洞前停下;④进程级 LostRange 不再被计入已上报,`unreported_global_lost_range_count` 可见;⑤旧字段语义回归钳:`persisted`/`processed_count`/`reason` 在各路径与改前一致(现有消费者列表见 Global Constraints)。
- [ ] Step 2: 红→实现→绿;全量(`worker.py`/`task_control.py` 消费端零改动即兼容,验证其测试)。Commit。

### Task 7: F10-7 回执终态 + `stop()` 有界排空

**Files:**
- Modify: `backend/packages/ansich/ansich/service.py`(评估回执状态解析 :373-441、`stop()` :1095-1110、`_writer_loop` 退出条件)
- Test: `backend/tests/ansich/test_receipt_terminality.py`、`backend/tests/ansich/test_bounded_stop.py`(新建)

回执(RA6):`_lost_observation_ids`(有界 4096 FIFO)在 `_record_batch_loss`/`_record_observation_loss`/毒信路径登记;状态解析顺序:队内/在飞→`pending`;追踪集→`failed`;DB 有 obs→现行逻辑;DB 无 obs 且不在队/在飞→`failed`(重启后推定)。stop(RA7):排空预算 `stop_drain_timeout_ms`,期间直试无退避,耗尽记 loss+WARNING 后返回;打断进行中的退避等待。

- [ ] Step 1: 失败测试:①录入评估→批撞 `storage_failure` 且穷尽(fake)→回执 `failed` 非 `pending`(F10-7 注册场景逐字复现);②「DB 无、队无」推定路径(绕过追踪集直接构造);③排队中/在飞绝不判 failed;④stop против死 DB 在预算内返回、余量记丢、WARNING 有;⑤stop 打断退避(不等满退避周期)。
- [ ] Step 2: 红→实现→绿;全量。Commit。

### Task 8: 后端收口 — 配置线程全验 + 故障注入组合回归

**Files:**
- Test: `backend/tests/ansich/test_write_resilience_integration.py`(新建;真 `create_sql_ansich_service` + SQLite,非 fake backend)
- Modify: 仅测试发现的接线缺口

组合场景(spec §10 queue/writer 行的落位):真 SQLite 后端下——瞬断注入(临时锁库/替换 session factory 抛错)→恢复→零丢失端到端;容量尾丢与账目一致性(accepted+dropped == 分配序号数,per-producer 合计 == 全局);`flush_task` 屏障在真后端的保序;设置全部新配置键经 `create_embedded_ansich_service` 传导(构造后反射断言)。

- [ ] Step 1: 红(组合断言先失败于未接线处或直接绿——直接绿的用例要用突变检验证明有牙:临时破坏一处接线看它红,报告里给证据)。
- [ ] Step 2: 绿;全量 `tests/ansich` + bootstrap + `uv run ruff format`/`check`。Commit。

### Task 9: 前端同步 — 类型镜像、attention 映射、健康抽屉展示

**Files:**
- Modify: `frontend/src/core/ansich/types.ts`(:115-140 `AnsichHealth` 镜像 + status 联合)、`frontend/src/core/ansich/presentation.ts`(attention/lifecycle 映射)、`frontend/src/components/workspace/ansich/system-health-drawer.tsx`(writer/producers 区块)、i18n zh+en
- Test: `frontend/tests/unit/core/ansich/presentation.test.ts`(扩展)

规则(RA10):`starting`/`shutting_down` 不触发横幅 attention(短暂生命周期态),`recovering` 触发(事故未了);新增值必须进 `isProjectionAttention` 与刚落地的分级横幅纯函数层(`resolveProjectionHealthDisplay` 的输入域扩展,关闭快照的 status 恶化序:healthy < recovering < degraded < failed/stopped;`starting`/`shutting_down` 不参与恶化比较——unknown 同款处理);抽屉新增 writer 块(退避中/连败/在飞/毒信计数)与 producers 表(有界,展示 top N by dropped)。文案不泄后端配置键名。

- [ ] Step 1: 失败测试(纯函数层):三个新状态的 attention 判定;恶化序含 `recovering` 的重弹判定;旧状态行为不变。
- [ ] Step 2: 红→实现→绿;`pnpm check && pnpm test` 全绿。Commit。

### Task 10: 文档与状态同步(同一 change set 收尾)

**Files:**
- Modify: `backend/AGENTS.md`(ansich 采集段:writer 重试/毒信/屏障/回执终态/lifecycle 新语义;不许再说「DB 异常整批丢失」形状)、`ansich/docs/plans/phase-10-review-followups.md`(F10-7 翻 ✅ 带 commit 哈希)、`ansich/docs/plans/README.md`(P11-A 状态条目:范围=spec §2+F10-7,P11-B/C 未开工;进程级范围「账目已诚实、持久化留待 B 的 host-Scope」这句必须写)、`ansich/docs/plans/11-resilience-replay-and-retention.md`(§2 末尾加一行实现状态指针)
- Test: 无(文档)

- [ ] Step 1: 逐文件改;`uv run ruff format`(只会碰 py,md 不动——保险);全量后端 + 前端各跑一遍作为收尾验证。Commit `docs(ansich): record P11-A write-resilience status`。

## Self-Review 记录

- Spec §2 覆盖对照:状态机(T2)、per-producer 账目(T3)、record 不阻塞(不变+T3 锁内纯操作)、terminal 不挤旧项(现状已满足,档案 §1.4 注)、无 spool/WAL 为 known limitation(T10 文档句)、writer 原子批(现状已满足)、有界退避不占调用栈(T4)、容量后 drop(现状+T4③)、毒信隔离(T5)、屏障 sequence 界定+返回形状(T6)、`{persisted_through, lost_ranges, timed_out}`(T1+T6)。§2 之外未越界:水位/Alert/lease/health-DB-merge 全部未触碰(B 批)。
- F10-7 注册场景在 T7① 逐字复现;RA8 两处假账在 T6 修正。
- 类型一致性:`ProducerHealth`/`WriterHealth`/新 Literal 在 T1 定义,T2-T9 引用同名同型;`persisted_through` 的「连续」语义 T6 与 T7(排空)一致。
- 无占位符;每任务有具体测试场景与锚点;执行者不读本文件之外的计划(brief 抽取制)。

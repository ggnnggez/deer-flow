# Ansich P11-B 多 worker 投影韧性与健康面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让投影/评估侧在多 worker PostgreSQL 下不双写、不互相覆盖 lease;毒作业与采集丢失获得 Alert 出口(host-Scope 进程主体);健康面合并数据库真相(每投影器计数/水位/lag);清偿全部并发债(F10-6/19/20/23/24/25/26/27 + 假说 (c))。

**Architecture:** lease 侧加 `lease_generation` 列(0027)做完成/出错写入的 CAS;`retry` 状态区分"从未尝试"与"重试中";rebuild/retry 在 PG 上取 `pg_advisory_lock` 成为单操作者维护操作。进程主体 = 启动期以哨兵 task_id 铸造的 host Scope(确定性 id,与环境探针的 host Scope 收敛);进程级丢失经新 kind `observability.lost`(scope 主体)落盘,两个新 Alert 生产者活在周期 `assess_operations` 里(评估作业机器 FK 绑死 Task,不可用)。健康 DB 合并走**独立异步方法、路由层合并**(`get_health` 的锁下纯度是 A 留下的最大结构约束),additive `database` 块。**一个迁移:0027**(两列 lease_generation + 一个 (projector_name,status) 索引;无新表)。

**Tech Stack:** Python 3.12 / SQLAlchemy async / Alembic / FastAPI / Next.js + TypeScript / PostgreSQL 16(opt-in tier)。

**Spec:** `ansich/docs/plans/11-resilience-replay-and-retention.md` §3/§4/§9(执行者必读;§2 已由 P11-A 落地,§5-8 归 C,勿越界)。现状事实以侦察档案为准:`/tmp/claude-1000/-home-nan-c-project-deer-flow/3783b205-4932-4864-a312-47c88df09488/scratchpad/p11b-recon-dossier.md`(锚点全部对 HEAD `b2ea0e48` 核实;service.py 行号已整体重排,sql.py 较旧档案 +2)。债项登记原文:`ansich/docs/plans/phase-10-review-followups.md` F10-19..28 与假说 (c)(F10-10 条)。

## Global Constraints

- `backend/packages/ansich/` 禁止 import deerflow/app/FastAPI/LangGraph(钳:`tests/ansich/test_contracts.py::test_ansich_core_has_no_deerflow_or_web_framework_imports`)。
- 采集/投影/评估 fail-open;`record()` 非阻塞;`get_health()` 保持同步、锁下、零 IO(DB 合并绝不进它)。
- **每个不变量声明其成立的域**(P11-A 终审教训):并发不变量必须写明覆盖的交错集合;测试按域取代表性交错,不许只测顺路径。
- **时钟规则(全局,源自 F10-24)**:任何 resolver/比较的决胜不得落在模拟钟与真实钟之间;fixture 时间戳一律过去日期;lease 过期测试用可注入时间。
- **评审探针必须入库**:评审用以确立 finding 的探针,在 finding 闭合前转为红先回归测试。
- **实现者串行**:任一时刻至多一个实现者持有 git index;评审只读 + monkeypatch 突变,不改树。
- **禁止截断输出的管道**:实现者/评审跑测试不得用 `tail`/`head` 截断可能含失败文本的输出;长跑套 shell `timeout` 并在长步骤间发一行进度。
- 迁移纪律:0027 一个 revision,幂等守卫(`safe_add_column`/inspector 先例 0026:42-55),可逆;head-pin 16 处 13 文件全数更新(档案 §4.3 有清单)+ 头测试函数改名 + backend/AGENTS.md 迁移列表条目。
- flake 协议:F10-10/rebuild 家族翻红→单跑复核、两个结果都报、全文入报告。
- 后端命令 `cd backend && PYTHONPATH=. uv run pytest ...`;格式**只用** `uv run ruff format`/`check`;前端 `pnpm check && pnpm test`。多 worker PG 证明的**执行场所**如实声明:opt-in tier(`DEER_FLOW_TEST_POSTGRES_URL`),开发者本机真 PG,CI 不跑(与 redis tier 同形,文档已载)。仓库无 pgserver 先例——执行者需自备 PG(tier 的 docker 一行命令在 backend/Makefile:33-38)。
- SQLite 上 `skip_locked` 渲染为空、双后端可见同一行——这**恰好**使 SQLite 成为完成侧 CAS 的确定性测试基底(显式交错:A 认领→操纵 lease_expires_at 过期→B 认领→A 完成必须空操作);认领侧排他与 READ COMMITTED 丢更新只有真 PG 能证伪。
- `_project_pending` 吞掉所有异常(service.py:2681-2683)——一切并发断言落在**数据库行**上,不落在服务返回值上。

## 裁决(不变量 + 成立域 + 错误代价;结构留给实现者,偏离须论证)

- **RB1 host-Scope 铸造 = 启动期 bootstrap 观测 + 缺主体即跳过。** 不变量:①SQL 后端的 `start()` 以确定性 `source_event_id`(`ansich:host-scope:{hostname}`)记录一条 `scope.snapshotted(scope_kind="host", external_ref=hostname, relation_role=None)`——producer 去重使其跨重启幂等;②task_id 用文档化哨兵常量 `ANSICH_BOOTSTRAP_TASK_ID`(固定 UUID4;observations.task_id 无 FK,可存;AGENTS 声明该哨兵下的观测为 bootstrap 记录,无对应 Task 实体);③scope id 与环境探针的 host Scope 确定性收敛(同 `scope_entity_id("host", hash)`,`_project_scope_snapshot` 的同一性检查通过);④两个 Alert 生产者在 Scope 实体缺席时**跳过并返回 0**(`_assess_environment` 的 candidate-empty 惯用法)——绝不抛、绝不悬挂主体;⑤重放安全:观测持久→rebuild 重建 Scope;alert 行 FK CASCADE 到实体(models.py:1125-1129)的时序由④+RB5(rebuild 单操作者)共同守住。域:{冷启动、既有库升级(mint 在流尾)、rebuild 重放、mint 写入本身失败(fail-open,生产者继续跳过)}。代价若错:进程级 Alert 迟到至 Scope 就位,期间事实仍在 unreported 桶/失败作业面可见。
- **RB2 进程级丢失 = 新 kind `observability.lost` v1(scope 主体),不改 `observability.degraded`。** 不变量:①`observability.degraded` 契约一字不动(冻结/strict,Task 主体,contracts.py:219-221);②新 kind 显式 `_validate_subject` 分支:subject_type="scope"、subject_id=host scope id、task_id=哨兵;payload 携带 first/last_sequence、producer 身份(与 degraded 同形);③A 留的 seam(`_unreported_global_ranges`,service.py:207-211/1664-1714)在存储恢复后经它落盘,成功后才从桶中移出并计入已上报——账目诚实规则延续;④不注册投影器(证据链只需行存在,档案 §3.4 选项 (a);晚加投影器会静默跳过历史——此性质写进 kind 的注释)。域:{Scope 未就位(留桶)、写入再失败(留桶)、重启(桶重建自内存——已知限制,AGENTS 已载)}。代价若错:多一个 kind 的维护面(两个 kind 本就是两类事实:有主与无主的丢失)。
- **RB3 两个 Alert 生产者活在周期 assess_operations,证据链各自成立。** 不变量:①assessor-job/watermark 机器 FK 绑死 ansich_tasks(models.py:129-133/204-208)——Scope 主体生产者**不得**触碰它,与 `_assess_environment` 并排(sql.py:4857);②`projection_failure` 证据 = 失败投影作业自带的 obs_id(models.py:86);**本批范围限定投影作业**——assessor 作业无 obs_id,该边界显式写进生产者 docstring 并在 F10-18 杂项挂一行(证据可由 evidence_watermark 反查,留待需要时);③`observability_degradation` 证据 = `observability.lost` 行;④reconcile 的穷尽契约(episodes.py:208-252):每个生产者对 host-Scope 主体的每次 reconcile 是**一次调用携带该 (rule, alert_type) 下的完整键集**——键:projection_failure 按 `(projector_name, projector_version)`,observability_degradation 按 producer 身份;域:{键集为空(全恢复→resolve 语义)、多键并存、复发编号}。⑤读侧:两个 AlertType 已存在(episodes.py:26-27),补 4 处线缆(条件分支、router 允许表、types.ts、locales)——前端 exhaustive switch 无 default 是免费强制函数(presentation.ts:14-33)。代价若错:告警面误报/漏报,底账(失败作业面、health 计数)不受影响。
- **RB4 lease CAS = 0027 的 `lease_generation` 列,完成/出错写入按代际守卫。** 不变量:①认领在同事务 `lease_generation += 1` 并记住代际;完成/出错/吸收写入 `WHERE job_id=:id AND lease_generation=:gen`,rowcount==0 即静默放弃(结果由新 owner 负责);②owner-only CAS 不充分的原因(同 owner 重认领 ABA:`_lease_owner` 进程内恒定,sql.py:754)写进列注释;③`retry` 状态:错误路径重臂置 `status='retry'`(pending 保留给从未尝试),认领谓词纳入 retry(sql.py:1330/1437 两处),`has_pending_for_task`(sql.py:1051)纳入;不重命名 processing(档案 §4.2 的 beware);④`retry_failed_projections` 只触 `status='failed'` 行(失败行无活 lease——错误路径已清)、返回值与真实重臂数一致;⑤投影器幂等性仍是兜底(CAS 失败的旧 worker 已完成的副作用由幂等吸收)。域:{两 worker 认领竞争、lease 过期后被夺、同 owner 过期重认领(ABA)、操作者 retry 与在飞完成交错、吸收路径(assessor 组)}。代价若错:双写回归到今天的现状(投影幂等使其安全但账目分叉)。
- **RB5 rebuild/retry 是单操作者维护操作。** 不变量:①PG 上 `rebuild_projections` 与 `retry_failed_projections` 全程持 `pg_advisory_lock`(bootstrap.py 先例;锁 id 常量文档化),第二操作者阻塞或明确拒绝(选其一并论证);②SQLite 语义不变(单 worker 约束已文档化);③`rebuild` 的 re-pend(sql.py:1129-1139)在锁内,不再能重臂另一 worker 在飞的行;④`service.py:1459-1460` 的注释更新为新真相。域:{rebuild∥worker 认领、rebuild∥retry、双 rebuild}。代价若错:重放期双写(幂等兜底)。
- **RB6 complete-through 水位 = 读时计算,不落存储列。** 不变量:①语义 = 每 (projector_name, projector_version) 上 `min(ingest_seq)-1` over 未结算作业(pending/retry/processing/failed)——**连续性**标记,非 max;②0027 加索引 `ix_ansich_projection_jobs_projector_status (projector_name, status)` 支撑分组计数;lag 用"未结算作业的 MIN(ingest_seq) 那一行的 recorded_at vs now"(单行索引查,档案 §7.2 的替代式——`recorded_at` 无索引,禁止全扫);③对 spec 字面("维护 projector watermark")的偏离记录:可观测性要求由读时计算满足,存储副本必然漂移。域:{零作业(水位=全局最高 ingest_seq)、全 failed、混态}。代价若错:健康页读延迟随作业表规模(索引使其有界)。
- **RB7 健康 DB 合并 = 独立 `async get_database_health()` + 路由层合并 + additive `database` 块。** 不变量:①`get_health()` 一字不动(同步、锁下、零 IO——它与 `record_batch` 共享 threading.Lock,DB 往返进锁 = 存储延迟直上采集热路;档案 §9.1);②新方法自带超时(新 knob `health_database_timeout_ms`,默认 2000)与 try/except:DB 不可达 → `database.status="unreachable"` + 进程侧数据照常返回(spec §4 原文);③DTO:additive `DatabaseHealth` 嵌套块(`status: Literal["reachable","unreachable"]`、per-projector 行:pending/retry/processing/failed 计数 + complete_through、`lag_ms`、`failed_jobs` 权威计数),`WriterHealth` 先例(contracts.py:670-676);④进程本地 `failed_jobs` 保名,AGENTS 声明其 advisory 性(漂移:投影失败路径不重算——档案 §9.9);只有 `database.failed_jobs` 是权威;⑤`GET /health` 仍是存储宕机可读的那一个端点(`_ensure_queryable` 语义不变)。**spec 冲突裁决**:§4"无 pending 有 failed ⇒ status failed"**拒绝**——与 A 的 17 边钳直接冲突(reachability 变化破坏被钉补集);其意图(失败不被掩盖)由 `database.failed_jobs`>0 + degraded 状态 + 告警承载;偏离入 T-docs。§3 `ORDER BY job_id` **拒绝**——破坏文档化的观测内投影优先序(sql.py:277-279/423-425);确定性意图由现有 (ingest_seq, priority, name) 序满足;偏离入 T-docs。域:{DB 可达/不可达/慢(超时)、两 worker 各自报告}。
- **RB8 读模型停止盖章进程本地指标。** 不变量:`_refresh_active_task_read_model` 里 `metrics = self.get_projection_metrics()`(sql.py:5466)替换为 DB 派生数(RB6/RB7 的同一批查询,在 ops tick 里算)——两 worker 下"谁最后 tick 谁的水位盖到全部 Task 行"的跨 worker 谎报(档案 §9.10)消除。域:{两 worker 交替 tick}。代价若错:ops tick 增加一次有界索引查询。
- **RB9 债项修法逐条钉死。** ①F10-6/F10-20:三处 rollup(`_refresh_behavior_belief` sql.py:2458 区、`_refresh_active_task_read_model` :5456 区、`_project_budget` :7213 区)+ `_refresh_usage_summary`(:7530 区)全部改为参考实现 `_recompute_release_quality_stats` 的 lock-then-read(先 `SELECT…FOR UPDATE` 锁目标行再读输入);首写者竞态以 `INSERT…ON CONFLICT DO NOTHING` 收口后重读。域:{两 worker 兄弟作业并发、行不存在的首写}。②假说 (c):`_claim_assessor_job` 记住 pre-claim 水位,`_advance_assessor_watermark` 推进到 `max(本次评估水位, pre-claim 水位)`——F10-10 条目里点名的缺失测试牙(`test_absorbed_low_watermark_window_survives_an_evaluation_rollback` 补 count 断言)必须落。域:{依赖延迟迟到作业、正常吸收、回滚重试}。③F10-19:spawn 投影完成后按后代 re-fanout 对账(幂等键已保证不双计);「贡献与 spawn 边并发到达时 inclusive 不丢」回归。④F10-23:`_assess_scope_safety_at` 走 `_claim_projection_job` 的 hydrate 惯用法(sql.py:1348-1355);「externalized 证据不产失败作业」回归(阈值压 16 逼出)。⑤F10-24:终端写者 `_assess_budget_rows` 的 value_json 收敛为评估器形状(补 enforcement/shadow 可知字段、保留 as_of_known);「两写者交错时读者形状稳定」回归;决胜仍跨钟但形状不再漂移(F10-24 剩余半边闭合,注册表翻绿)。⑥F10-25:包边界类型化 `StorageUnavailableError`(packages/ansich 内定义,不 import SQLAlchemy——harness 侧转译),router 既有 503 路径接住;回执语义不变(不是 failed)。⑦F10-26:`rebuild_projections` 完成条件计入 dependency-pending 作业——等待其结算或越过 `projector_dependency_timeout` 转 durable failed,**或**在返回值显式报告未结算数(选一并论证);「依赖延迟未结算时重建不静默报完成」回归(250ms 窗口机制已由代码读定,档案 §9.16)。⑧F10-27:两装配分支共用 knob 映射(结构上不可能漏传)+ `operations_assessment_interval_ms` 补 `AnsichConfig` 字段(startup-only,example.yaml 同步)。
- **RB10 多 worker 证明分层。** 不变量:①SQLite(合并门禁内):完成侧 CAS、retry 谓词、水位读——显式交错、确定性;②真 PG(opt-in tier):两 engine 两 service 一库——认领排他(SKIP LOCKED 真语义)、rebuild advisory 锁、F10-6/20 的丢更新证伪(改前红/改后绿至少一例)、健康计数跨 worker 一致;③settle 门禁按 service 各上各的(`only_test_driven_assessments` 是 per-service——两个都要上,档案 §6.2);④执行场所声明:tier 由开发者本机真 PG 执行,CI 不跑——AGENTS 的既有诚实条目延续,验收 = tier 全绿的实跑输出入报告。域:{两 worker × (认领/完成/出错/retry/rebuild) × lease 过期}。
- **RB11 前端 = Observability Health 面板(数据库/投影视图)+ 告警类型接线,收尾任务。** 不变量:①新读路径(api fn + hook + query key)打 `GET /api/ansich/health`——前端今天从不读它(档案 §7.4);②面板 = per-projector 行(计数拆分/水位/lag)+ `database.status`,放 operations 页(实现者定 tab 或段落,与既有布局一致);③抽屉不动(进程/采集墙),分界线写进两个组件的 docstring;④两个新 AlertType 过 exhaustive switch(5 文件);⑤文案不泄配置键名,`database.failed_jobs` 与进程 `failed_jobs` 的措辞区分(权威 vs 进程视角)。

---

### Task 1: 迁移 0027 — lease_generation 两列 + projector-status 索引 + head-pin 全量

**Files:** Create `backend/packages/harness/deerflow/persistence/migrations/versions/0027_ansich_lease_generation.py`;Modify `models.py`(AnsichProjectionJobRow ~:81-99、AnsichAssessorJobRow ~:125-163 各加 `lease_generation: Mapped[int] = BigInteger, NOT NULL, server_default "0"`;jobs 表加索引);16 处 head-pin(档案 §4.3 清单)+ 头测试改名;backend/AGENTS.md 迁移列表。
**Interfaces:** Produces:两列名 `lease_generation`;索引名 `ix_ansich_projection_jobs_projector_status (projector_name, status)`。
- [ ] 红先:bootstrap 头测试断言新 head;迁移往返测试(upgrade→downgrade→upgrade 幂等,0026 先例的 inspector 守卫);全量 `tests/ansich` + 全部 bootstrap 文件绿。Commit `feat(persistence): 0027 ansich lease generation and projector-status index`。

### Task 2: lease CAS + retry 状态 + retry/rebuild 单操作者化(RB4+RB5)

**Files:** `sql.py`(认领 :1338-1349/:1480-1500 区、完成 :990-997/:1722-1729、错误路径 :1360-1418/:1504-1552、retry_failed_projections :1169-1202、rebuild :1058-1148)、`service.py`(rebuild/retry 包装)、Test `tests/ansich/test_lease_cas.py`(新)。
要点:代际 CAS(RB4①);retry 状态全谓词接线(RB4③);retry 只触 failed(RB4④);PG advisory lock 包 rebuild/retry(RB5,SQLite no-op);sql.py:1459-1460 注释更新;**SQLite 确定性交错测试**(Global Constraints 的显式交错脚本:A 认领→注入过期→B 认领→A 完成 rowcount 0→B 完成生效;错误路径同型;吸收路径同型)。
- [ ] 红先(A 完成覆盖 B 的现状先钉红)→实现→绿;突变(去掉 WHERE 代际→红);全量。Commit。

### Task 3: 假说 (c) 修复 + F10-26 rebuild 完整性(RB9②⑦)

**Files:** `sql.py`(claim 宽化 :1489-1495 区、advance :1703-1708/:1812-1820 区、rebuild 完成条件 :1147 区)、Test 扩展 `test_sql_safety.py`(F10-10 点名的 count 断言)+ `test_sql_alerts.py`/rebuild 测试。
要点:pre-claim 水位记忆与恢复;rebuild 对 dependency-pending 的等待-或-显式报告(RB9⑦ 选型入报告);F10-10/F10-26 注册表在 T-docs 翻绿的证据在此产出。**这是 F10-10 flake 家族的根治任务**——落地后在争用 harness 下跑一轮 gated 测试作为证据(`tests/support/ansich_contention_repro.sh`,小轮数)。
- [ ] 红先(count 断言在现行代码红——假说 (c) 的宽窗重判)→实现→绿;harness 轮次证据入报告;全量。Commit。

### Task 4: F10-23 hydrate + F10-25 类型化存储错误(RB9④⑥)

**Files:** `sql.py`(`_assess_scope_safety_at` :1918-1945 区)、`packages/ansich/ansich/errors.py`(新,StorageUnavailableError)、`service.py`(record_evaluation :700-760 区 try 转译)、harness 侧转译点、router(既有 503 路径确认)、Tests。
- [ ] 红先(externalized 证据产失败作业先钉红,阈值 16;存储宕机中 record_evaluation 抛裸异常先钉红)→实现→绿;全量。Commit。

### Task 5: F10-6 + F10-20 lock-then-read 收口(RB9①)

**Files:** `sql.py` 四处(三 rollup + usage summary),Test `tests/ansich/test_rollup_serialization.py`(新;SQLite 侧断言锁形状与 ON CONFLICT 语义、行为回归;真正的丢更新证伪归 Task 9 PG)。
- [ ] 参考实现形状逐处对齐(先锁目标行后读输入;首写 ON CONFLICT);行为零变化回归(全量绿);形状钉(每处一个"锁先于读"的结构测试或注释+T9 证伪指针)。Commit。

### Task 6: F10-19 spawn re-fanout 对账(RB9③)

**Files:** `sql.py`(spawn 投影完成处 + `_backfill_spawn_usage` :6822-6886 区)、Test 扩展 task-tree/usage 测试。
- [ ] 红先(并发到达丢贡献的场景可在 SQLite 显式交错模拟:贡献投影在 spawn 边可见前跑完→祖先缺口)→re-fanout 实现(幂等)→绿;全量。Commit。

### Task 7: host-Scope 铸造 + `observability.lost` + 桶落盘(RB1+RB2)

**Files:** `contracts.py`(新 kind + `_validate_subject` 分支 + `ANSICH_BOOTSTRAP_TASK_ID` 常量 + envelope 构造器)、`service.py`(start() 铸造;`_report_degradation_if_storage_recovered` 扩展:桶经新 kind 落盘、成功才出桶)、Tests(契约 + 服务:铸造幂等/重启收敛/桶落盘/失败留桶/Scope 缺席跳过)。
- [ ] 红先→实现→绿;重放测试(rebuild 后 Scope 重建、桶落盘的行存活);全量。Commit。

### Task 8: 两个 Alert 生产者 + 类型接线(RB3)

**Files:** `sql.py`(assess_operations 里新增两 pass,`_assess_environment` 并排;候选=host Scope 存在才跑)、`episodes.py`(条件分支)、router 允许表(:506-519 区)、Tests(`test_sql_alerts.py` 扩展:开→确认→resolve→复发编号;穷尽契约——一次调用完整键集;Scope 缺席返回 0;评估器作业失败不产 projection_failure——边界钉)。
- [ ] 红先→实现→绿;全量。Commit。

### Task 9: 双 worker PG tier 扩展(RB10②)

**Files:** `tests/integration/test_postgres_multiworker.py`(新;复用 `_postgres_engine` 形状,两 engine 两 service 一库,双 settle 门禁)。
场景:认领排他(SKIP LOCKED 真语义:N 作业两 worker 认领无交集)、完成 CAS(过期夺取后旧 worker no-op)、rebuild advisory 锁(rebuild∥claim 排他)、F10-6/20 丢更新证伪(**至少一例改前红**:检出旧代码路径可用 monkeypatch 临时还原未锁版本证伪,或以并发压勾出;拿不到红则如实降级为"改后并发绿"并声明)、健康计数跨 worker 一致(RB7 的 DB 权威数两边读一致)。执行:开发者本机真 PG(`DEER_FLOW_TEST_POSTGRES_URL`),实跑输出入报告;CI 不跑(声明)。
- [ ] 实现→tier 实跑绿(输出入报告)→默认套件不受影响(自跳)。Commit。

### Task 10: 健康 DB 合并 + 读模型盖章修复 + F10-24/27(RB6+RB7+RB8+RB9⑤⑧)

**Files:** `contracts.py`(DatabaseHealth 块)、`sql.py`(`get_database_health` 查询组:分组计数/complete-through/lag 的索引友好式;`_refresh_active_task_read_model` :5466 盖章替换;`_assess_budget_rows` 形状收敛)、`service.py`(异步方法透传)、router(`GET /health` 路由层合并 + 超时)、`ansich_config.py`(`health_database_timeout_ms`、`operations_assessment_interval_ms` 补字段)、装配两分支共用 knob 映射(F10-27)、config.example.yaml、Tests(DB 不可达→unreachable+进程侧照常;计数/水位/lag 正确性;形状稳定回归;装配对称钉)。
- [ ] 红先→实现→绿;全量(含 bootstrap 全家 + reload_boundary 钉)。Commit。

### Task 11: 前端 — Observability Health 面板 + 告警类型(RB11)

**Files:** `frontend/src/core/ansich/`(api fn + hook + types:DatabaseHealth 镜像)、`components/workspace/ansich/observability-health-panel.tsx`(新)、operations 页接线、`types.ts`/`presentation.ts`(两 AlertType 过 exhaustive switch)、locales ×3、Tests(纯层:面板选择器/计数格式;e2e 桩:面板行渲染 + 新告警类型入 filter)。
- [ ] 红先→实现→绿;`pnpm check && pnpm test` + 本地 e2e 实跑。Commit。

### Task 12: 文档与状态收口

**Files:** backend/AGENTS.md(lease/CAS/retry/rebuild 单操作者/健康双数语义/host-Scope 哨兵/observability.lost/两生产者边界/两处 spec 字面偏离(ORDER BY job_id、failed⇒failed)/多 worker 证明场所);注册表翻绿:F10-6/19/20/23/24/25/26/27 + 假说 (c)(F10-10 条)带 commit;F10-10 留观更新(根治后的观察语句);README P11-A 条目后接 P11-B 条目;`11-...md` §3/§4/§9 实现状态指针;concepts 如涉及。收尾全量双端验证。
- [ ] Commit `docs(ansich): record P11-B multiworker resilience`。

## Self-Review 记录

- §3 覆盖:lease CAS(T1/T2)、poison→projection_failure(T8)、observability_degradation(T7/T8)、进程主体映射(T7,RB1)、SKIP LOCKED 修正(RB4;ORDER BY job_id 拒绝有记录)。§4:多级水位(RB6 读时计算,偏离有记录)、lag 语义(RB7 索引友好式)、known/unknown(RB2 落盘使 unreported 桶可清)、task 交集(RB8 盖章修复)、failed⇒failed 拒绝有记录。§9:health 合并(T10)、面板(T11)。债项:RB9 八条各有任务与回归。域声明:每条 RB 带域;两处 spec 字面偏离在 RB7 内裁决并入 T12 记录。类型一致:`lease_generation`/`retry`/`DatabaseHealth`/`ANSICH_BOOTSTRAP_TASK_ID`/`observability.lost` 名称在产出任务定义、后续任务逐字引用。无占位符;每任务锚点来自档案(HEAD b2ea0e48 核实)。

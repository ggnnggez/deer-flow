# Ansich 环境观测(OS 级信号)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把沙箱执行环境的 OS 级信号(fd、io、内存、磁盘、PSI)作为第二类证据来源接入 Ansich:Observation → typed projection → Belief/Alert 全链路,Alert subject 为 sandbox/host Scope,Task 侧可反查。

**Architecture:** 新增 `environment.sampled` Observation(subject 为 Scope),由两条采集路径产生——AIO 容器/local 宿主的周期 probe(仿 `AnsichTaskHeartbeat`)和 local bash 的按命令进程组采样(经现有 tool probe 链发射)。`environment-projector@1` 投影为"现状行"读模型;`environment-pressure@1` 在现有周期 operations 评估循环中产生仅类别跃迁追加的 Assertion 和进现有 episode 状态机的 AlertCondition。

**Tech Stack:** Python 3.12 / Pydantic / SQLAlchemy async / Alembic / FastAPI / Next.js + TypeScript。

**Spec:** `docs/superpowers/specs/2026-08-19-ansich-environment-observability-design.md`(执行者必读;本计划的每个决定都以它为准)。

## Global Constraints

- `backend/packages/ansich/` 禁止 import `deerflow`、`app`、FastAPI、LangGraph(被 `tests/test_harness_boundary.py` 与包纪律约束)。
- `backend/packages/harness/deerflow/` 禁止 import `app.*`。
- 采集/投影/评估全部 fail-open:任何失败只 log,不影响 DeerFlow Run。
- 事件循环上禁止阻塞 IO:`/proc`、cgroup、磁盘读取必须经 `asyncio.to_thread`(CI 有 blocking-io 门禁)。
- 断言只在类别跃迁时追加;assertion 的 `value_json` 只放稳定类别字段,数值留读模型(否则每 tick 追加断言,违反 spec §5.2)。
- 缺数据永远是 `unknown`,不是 `ok`;`environment_scope`/`coverage` 标记全链路不可丢失。
- `process_group` 与 `host_shared` 数据永远不喂泄漏规则(spec §5.2)。
- 每个 ORM 变更必须有 alembic revision;本计划使用 `0026_ansich_environment`。
- backend 测试命令:`cd backend && PYTHONPATH=. uv run pytest tests/<file> -v`;全量 `make test`;格式 `make format`。
- 前端:`cd frontend && pnpm check && pnpm test`。
- 泄漏规则默认阈值(spec 定值):M=6 个连续增长样本、W=60 秒、净增 N=50。
- fd 阈值:warn 0.8 / critical 0.95;磁盘余量比:warn 0.10 / critical 0.05;PSI avg10(×1000 存整数):warn 40000 / critical 80000。
- v1 指标名固定集合:`fd_open`(limit=软限)、`io_read_bytes`、`io_write_bytes`、`rss_bytes`、`disk_free_bytes`(limit=总容量)、`psi_io_some_avg10_milli`、`psi_memory_some_avg10_milli`。

## 与 spec 的两处实现级偏差(有意,已论证)

1. **`possibly_affected_task_ids` 不进 assertion value,也不作为 alert evidence obs**:它随运行中 Task 集合变化,放进 `value_json` 会破坏"仅跃迁追加"去重。落点改为 alert 读模型行的附加 JSON 列(reconcile 变更时刷新),alert evidence 仍是贡献样本的 obs 引用。语义不变("采样时正在运行"),存储位置从 evidence 挪到读模型。
2. **local 的连续 tick 同时声明两个 Scope**:host Scope(承载 host_shared 读数)和 sandbox Scope(`local:{thread_id}`,per_command 样本的 subject)。因为 per_command 观测需要 sandbox Scope 实体存在,而 local 的连续读数挂在 host Scope 上。

---

### Task 1: 契约层 — `environment.sampled` kind、payload 模型、ScopeKind/Role 扩展、envelope 构造器

**Files:**
- Create: `backend/packages/ansich/ansich/environment.py`
- Modify: `backend/packages/ansich/ansich/contracts.py`(ObservationKind 联合、`_validate_subject`、两个 classmethod)
- Modify: `backend/packages/ansich/ansich/safety.py`(`ScopeKind` += `"host"`,`ScopeRelationRole` += `"host_environment"`)
- Test: `backend/tests/ansich/test_contracts_environment.py`

**Interfaces:**
- Produces(后续所有任务依赖):
  - `ansich.environment.EnvironmentScopeKind = Literal["container", "process_group", "host_shared"]`
  - `ansich.environment.EnvironmentCoverage = Literal["continuous", "per_command", "uninstrumented"]`
  - `ansich.environment.EnvironmentMetric(value: int, limit: int | None)`
  - `ansich.environment.EnvironmentWindow(started_at: datetime, ended_at: datetime, sample_count: int)`
  - `ansich.environment.EnvironmentSamplePayload(environment_scope, coverage, window, provider, metrics: dict[str, EnvironmentMetric], tool_call_id: str | None)`
  - `ObservationEnvelope.environment_sampled(...) -> Self`
  - `ObservationEnvelope.scope_snapshotted(...) -> Self`

- [ ] **Step 1: 写失败测试**

`backend/tests/ansich/test_contracts_environment.py`(参考同目录现有测试的 envelope 构造方式):

```python
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from ansich.contracts import ObservationEnvelope
from ansich.environment import EnvironmentSamplePayload
from ansich.safety import scope_entity_id, scope_reference_hash


def _scope_id() -> str:
    return scope_entity_id("sandbox", scope_reference_hash("sandbox", "local:thread-1"))


def _payload(**overrides) -> dict:
    base = {
        "environment_scope": "container",
        "coverage": "continuous",
        "window": {
            "started_at": datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC),
            "ended_at": datetime(2026, 8, 19, 12, 0, 10, tzinfo=UTC),
            "sample_count": 1,
        },
        "provider": "aio",
        "metrics": {"fd_open": {"value": 120, "limit": 1024}},
        "tool_call_id": None,
    }
    base.update(overrides)
    return base


def _envelope(payload: dict) -> ObservationEnvelope:
    return ObservationEnvelope.environment_sampled(
        task_id=str(uuid4()),
        run_id="run-1",
        occurred_at=datetime(2026, 8, 19, 12, 0, 10, tzinfo=UTC),
        scope_id=_scope_id(),
        payload=payload,
        source_event_id="run:run-1:env:s:1",
    )


def test_environment_sampled_builder_produces_scope_subject():
    envelope = _envelope(_payload())
    assert envelope.kind == "environment.sampled"
    assert envelope.subject_type == "scope"
    assert envelope.subject_id == _scope_id()


def test_environment_sampled_rejects_missing_marks():
    payload = _payload()
    del payload["environment_scope"]
    with pytest.raises(ValueError):
        _envelope(payload)


def test_uninstrumented_requires_empty_metrics_and_zero_samples():
    with pytest.raises(ValueError):
        _envelope(_payload(coverage="uninstrumented"))
    payload = _payload(coverage="uninstrumented", metrics={})
    payload["window"]["sample_count"] = 0
    assert _envelope(payload).payload["coverage"] == "uninstrumented"


def test_per_command_requires_tool_call_id_and_process_group():
    with pytest.raises(ValueError):
        _envelope(_payload(coverage="per_command", environment_scope="process_group"))
    ok = _payload(
        coverage="per_command",
        environment_scope="process_group",
        tool_call_id=str(uuid4()),
    )
    assert _envelope(ok).payload["tool_call_id"] is not None
    with pytest.raises(ValueError):
        _envelope(_payload(tool_call_id=str(uuid4())))  # continuous 不许携带


def test_metrics_never_write_zero_for_missing_dimension():
    payload = _payload(metrics={"io_read_bytes": {"value": 5}})
    envelope = _envelope(payload)
    assert "fd_open" not in envelope.payload["metrics"]


def test_instrumented_sample_requires_metrics():
    with pytest.raises(ValueError):
        _envelope(_payload(metrics={}))


def test_host_scope_kind_and_role_exist():
    from ansich.safety import ScopeDescriptor

    host_id = scope_entity_id("host", scope_reference_hash("host", "my-host"))
    descriptor = ScopeDescriptor(
        scope_id=host_id,
        scope_kind="host",
        external_ref_hash=scope_reference_hash("host", "my-host"),
        display_label="host:my-host",
        created_obs_id=str(uuid4()),
    )
    assert descriptor.scope_kind == "host"


def test_scope_snapshotted_builder():
    from ansich.safety import scope_display_label

    ref_hash = scope_reference_hash("sandbox", "local:thread-1")
    obs = ObservationEnvelope.scope_snapshotted(
        task_id=str(uuid4()),
        run_id="run-1",
        occurred_at=datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC),
        scope_kind="sandbox",
        external_ref="local:thread-1",
        relation_role="sandbox_boundary",
        source_event_id="run:run-1:env-scope:sandbox",
    )
    assert obs.kind == "scope.snapshotted"
    assert obs.subject_id == scope_entity_id("sandbox", ref_hash)
    assert obs.payload["relation_role"] == "sandbox_boundary"
    assert obs.payload["scope"]["display_label"] == scope_display_label("sandbox", "local:thread-1")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_contracts_environment.py -v`
Expected: FAIL(`ModuleNotFoundError: ansich.environment` / `AttributeError: environment_sampled`)

- [ ] **Step 3: 实现 `ansich/environment.py`(payload 模型)**

```python
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

EnvironmentScopeKind = Literal["container", "process_group", "host_shared"]
EnvironmentCoverage = Literal["continuous", "per_command", "uninstrumented"]

_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EnvironmentMetric(_FrozenModel):
    value: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=0)


class EnvironmentWindow(_FrozenModel):
    started_at: datetime
    ended_at: datetime
    sample_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_window(self) -> Self:
        if self.ended_at < self.started_at:
            raise ValueError("environment window ended_at must not precede started_at")
        return self


class EnvironmentSamplePayload(_FrozenModel):
    environment_scope: EnvironmentScopeKind
    coverage: EnvironmentCoverage
    window: EnvironmentWindow
    provider: str = Field(min_length=1, max_length=64)
    metrics: dict[str, EnvironmentMetric] = Field(default_factory=dict)
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def _validate_marks(self) -> Self:
        for name in self.metrics:
            if not _METRIC_NAME.match(name):
                raise ValueError(f"environment metric name is not canonical: {name!r}")
        if self.coverage == "uninstrumented":
            if self.metrics:
                raise ValueError("uninstrumented environment sample must not carry metrics")
            if self.window.sample_count != 0:
                raise ValueError("uninstrumented environment sample must declare sample_count=0")
        elif not self.metrics:
            raise ValueError("instrumented environment sample requires at least one metric")
        if self.coverage == "per_command":
            if self.tool_call_id is None:
                raise ValueError("per_command environment sample requires tool_call_id")
            if self.environment_scope != "process_group":
                raise ValueError("per_command environment sample must be process_group scoped")
        elif self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid for per_command coverage")
        return self
```

- [ ] **Step 4: 扩展 `safety.py` 与 `contracts.py`**

`safety.py`:`ScopeKind` Literal 追加 `"host"`;`ScopeRelationRole` Literal 追加 `"host_environment"`。

`contracts.py`:
1. 顶部 kind Literal 区(第 45 行附近)追加 `EnvironmentObservationKind = Literal["environment.sampled"]`,并把它并入 `ObservationKind` 联合(找到现有联合定义,追加 `| EnvironmentObservationKind`)。
2. `_validate_subject`(`scope.snapshotted` 分支之后)追加:

```python
        elif self.kind == "environment.sampled":
            if self.subject_type != "scope":
                raise ValueError("environment observation subject_type must be scope")
            if self.payload is None:
                raise ValueError("environment observation requires a payload")
            from ansich.environment import EnvironmentSamplePayload

            EnvironmentSamplePayload.model_validate(self.payload, strict=False)
```

3. 仿照 `task_heartbeat`(contracts.py:385 附近)追加两个 classmethod:

```python
    @classmethod
    def environment_sampled(
        cls,
        *,
        task_id: str,
        run_id: str,
        occurred_at: datetime,
        scope_id: str,
        payload: dict[str, object],
        source_event_id: str,
        producer_seq: int = 1,
        producer_name: str = "environment-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        return cls(
            kind="environment.sampled",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_type="scope",
            subject_id=scope_id,
            producer=Producer(name=producer_name, version=producer_version, instance_id=producer_instance_id),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=run_id,
            payload=payload,
        )

    @classmethod
    def scope_snapshotted(
        cls,
        *,
        task_id: str,
        run_id: str,
        occurred_at: datetime,
        scope_kind: str,
        external_ref: str,
        relation_role: str | None,
        source_event_id: str,
        parent_scope_id: str | None = None,
        producer_seq: int = 1,
        producer_name: str = "environment-probe",
        producer_version: str = "1",
        producer_instance_id: str = "local",
    ) -> Self:
        from ansich.safety import scope_display_label, scope_entity_id, scope_reference_hash

        ref_hash = scope_reference_hash(scope_kind, external_ref)  # type: ignore[arg-type]
        scope_id = scope_entity_id(scope_kind, ref_hash)  # type: ignore[arg-type]
        obs_id = new_id()
        payload: dict[str, object] = {
            "scope": {
                "scope_id": scope_id,
                "scope_kind": scope_kind,
                "external_ref_hash": ref_hash,
                "display_label": scope_display_label(scope_kind, external_ref),  # type: ignore[arg-type]
                "parent_scope_id": parent_scope_id,
                "created_obs_id": obs_id,
            }
        }
        if relation_role is not None:
            payload["relation_role"] = relation_role
        return cls(
            obs_id=obs_id,
            kind="scope.snapshotted",
            occurred_at=occurred_at,
            task_id=task_id,
            subject_type="scope",
            subject_id=scope_id,
            producer=Producer(name=producer_name, version=producer_version, instance_id=producer_instance_id),
            producer_seq=producer_seq,
            source_event_id=source_event_id,
            correlation_id=run_id,
            payload=payload,
        )
```

注意:`scope.snapshotted` 的 `within_scope` 关系投影读取 payload 的 `relation_role` 与 `within_scope_subject_id`(缺省即 `observation.task_id`,见 sql.py:8040),所以 builder 不必显式传 subject。

- [ ] **Step 5: 跑测试通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_contracts_environment.py -v`
Expected: PASS

- [ ] **Step 6: 回归旧契约测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/ -k contract -v`
Expected: PASS(ScopeKind 扩展不破坏现有 scope 测试)

- [ ] **Step 7: Commit**

```bash
git add backend/packages/ansich/ansich/environment.py backend/packages/ansich/ansich/contracts.py backend/packages/ansich/ansich/safety.py backend/tests/ansich/test_contracts_environment.py
git commit -m "feat(ansich): environment.sampled contract, payload marks, host scope kind"
```

---

### Task 2: AnsichConfig 配置键

**Files:**
- Modify: `backend/packages/harness/deerflow/config/ansich_config.py`
- Test: `backend/tests/test_ansich_config.py`(若无此文件则新建;先 `ls backend/tests | grep ansich_config` 确认)

**Interfaces:**
- Produces:
  - `AnsichConfig.environment_probe_enabled: bool = True`
  - `AnsichConfig.environment_sample_interval_seconds: int | None = None`(None → 用 `heartbeat_interval_seconds`)
  - `AnsichConfig.environment_per_command_sampling: bool = True`
  - `AnsichConfig.effective_environment_sample_interval_seconds` property → int
  - `AnsichAssessorConfig` 新字段:`environment_fd_warn_ratio=0.8`、`environment_fd_critical_ratio=0.95`、`environment_disk_free_warn_ratio=0.10`、`environment_disk_free_critical_ratio=0.05`、`environment_psi_warn_milli=40000`、`environment_psi_critical_milli=80000`、`environment_leak_min_samples=6`、`environment_leak_window_seconds=60`、`environment_leak_min_growth=50`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from deerflow.config.ansich_config import AnsichConfig


def test_environment_defaults():
    config = AnsichConfig()
    assert config.environment_probe_enabled is True
    assert config.environment_sample_interval_seconds is None
    assert config.effective_environment_sample_interval_seconds == config.heartbeat_interval_seconds
    assert config.environment_per_command_sampling is True
    assert config.assessors.environment_leak_min_samples == 6


def test_environment_interval_override_and_bounds():
    config = AnsichConfig(environment_sample_interval_seconds=5)
    assert config.effective_environment_sample_interval_seconds == 5
    with pytest.raises(ValueError):
        AnsichConfig(environment_sample_interval_seconds=0)


def test_environment_threshold_ordering():
    with pytest.raises(ValueError):
        AnsichConfig(assessors={"environment_fd_warn_ratio": 0.96, "environment_fd_critical_ratio": 0.95})
```

- [ ] **Step 2: 跑测试确认失败**(`AttributeError`)

- [ ] **Step 3: 实现**

`AnsichAssessorConfig` 加 9 个 `Field`(约束:ratio 均 `gt=0, le=1`,milli/samples/seconds/growth 均 `ge=1`),并加 `model_validator(mode="after")` 校验 `warn < critical`(fd ratio 与 psi;磁盘方向相反:`disk_free_critical_ratio < disk_free_warn_ratio`)。`AnsichConfig` 加 3 个字段(interval `ge=1` 用 `Field(default=None, ge=1)`)和 property:

```python
    @property
    def effective_environment_sample_interval_seconds(self) -> int:
        return self.environment_sample_interval_seconds or self.heartbeat_interval_seconds
```

- [ ] **Step 4: 跑测试通过;Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/config/ansich_config.py backend/tests/test_ansich_config.py
git commit -m "feat(ansich): environment probe and assessor config keys"
```

---

### Task 3: local 按命令进程组采样(sandbox 层,零 ansich 依赖)

**Files:**
- Create: `backend/packages/harness/deerflow/sandbox/telemetry.py`
- Modify: `backend/packages/harness/deerflow/sandbox/local/local_sandbox.py`(`_run_posix_command`,538 行附近)
- Test: `backend/tests/test_local_sandbox_telemetry.py`

**Interfaces:**
- Produces:
  - `deerflow.sandbox.telemetry.CommandResourceSample(started_at, ended_at, sample_count, io_read_bytes: int | None, io_write_bytes: int | None, fd_peak: int | None)`
  - `set_per_command_sampling_enabled(enabled: bool) -> None` / `per_command_sampling_enabled() -> bool`(进程级开关,默认 False;由 Task 5 的 Gateway 装配在 ansich 启用时打开)
  - `consume_command_sample() -> CommandResourceSample | None`(取出并清空 ContextVar;Task 6 的 tool probe 消费)
  - `ProcessGroupSampler(pgid, proc_root=Path("/proc"), interval_seconds=1.0)`,`start()`,`stop() -> CommandResourceSample`

- [ ] **Step 1: 写失败测试**

```python
import subprocess
import sys
import time
from pathlib import Path

import pytest

from deerflow.sandbox import telemetry
from deerflow.sandbox.telemetry import ProcessGroupSampler

pytestmark = pytest.mark.skipif(not Path("/proc").exists(), reason="requires /proc")


def test_sampler_collects_io_and_fd_from_real_process_group():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; open('/dev/null','wb').write(b'x'*65536); time.sleep(3)"],
        start_new_session=True,
    )
    try:
        import os

        sampler = ProcessGroupSampler(os.getpgid(process.pid), interval_seconds=0.2)
        sampler.start()
        time.sleep(1.0)
        sample = sampler.stop()
    finally:
        process.kill()
        process.wait()
    assert sample.sample_count >= 1
    assert sample.fd_peak is not None and sample.fd_peak >= 3
    assert sample.io_write_bytes is not None and sample.io_write_bytes >= 65536


def test_short_command_yields_zero_samples_not_crash():
    sampler = ProcessGroupSampler(pgid=999999999, interval_seconds=0.2)
    sampler.start()
    sample = sampler.stop()
    assert sample.sample_count == 0
    assert sample.io_read_bytes is None  # 未采到不写零


def test_context_var_publish_consume_roundtrip():
    assert telemetry.consume_command_sample() is None
    sampler = ProcessGroupSampler(pgid=999999999, interval_seconds=0.2)
    sampler.start()
    telemetry.publish_command_sample(sampler.stop())
    assert telemetry.consume_command_sample() is not None
    assert telemetry.consume_command_sample() is None


def test_local_sandbox_publishes_sample_when_enabled(tmp_path):
    from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider

    telemetry.set_per_command_sampling_enabled(True)
    try:
        provider = LocalSandboxProvider(base_dir=str(tmp_path))
        sandbox = provider.acquire()
        sandbox.execute_command("head -c 4096 /dev/zero > /dev/null")
        sample = telemetry.consume_command_sample()
        assert sample is not None
    finally:
        telemetry.set_per_command_sampling_enabled(False)
```

注:`LocalSandboxProvider` 构造参数以实际签名为准——先执行
`grep -n "def __init__" backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py`
并按现有测试(`grep -rl LocalSandboxProvider backend/tests | head -3`)的构造方式改写最后一个用例的装配。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 `telemetry.py`**

```python
"""Per-command process-group resource sampling for the local sandbox.

Ansich-free by design: this module publishes plain data through a ContextVar;
the Ansich tool probe (deerflow/ansich/tool_middleware.py) is the only
consumer that turns it into observations. Undercount is expected and honest:
group members that exit between samples stop contributing, and /proc/<pid>/io
of already-reaped children is unreadable — coverage is declared per_command,
never a stock reading.
"""

from __future__ import annotations

import logging
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_ENABLED = False


def set_per_command_sampling_enabled(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = bool(enabled)


def per_command_sampling_enabled() -> bool:
    return _ENABLED


@dataclass(frozen=True)
class CommandResourceSample:
    started_at: datetime
    ended_at: datetime
    sample_count: int
    io_read_bytes: int | None
    io_write_bytes: int | None
    fd_peak: int | None


_LAST_SAMPLE: ContextVar[CommandResourceSample | None] = ContextVar(
    "deerflow_last_command_resource_sample", default=None
)


def publish_command_sample(sample: CommandResourceSample) -> None:
    _LAST_SAMPLE.set(sample)


def consume_command_sample() -> CommandResourceSample | None:
    sample = _LAST_SAMPLE.get()
    _LAST_SAMPLE.set(None)
    return sample


def _pgid_of(stat_path: Path) -> int | None:
    try:
        raw = stat_path.read_text()
    except OSError:
        return None
    # /proc/<pid>/stat: comm 可能含空格/括号,从最后一个 ')' 之后切分。
    tail = raw.rsplit(")", 1)[-1].split()
    try:
        return int(tail[2])  # state ppid pgrp → index 2
    except (IndexError, ValueError):
        return None


class ProcessGroupSampler:
    def __init__(self, pgid: int, *, proc_root: Path = Path("/proc"), interval_seconds: float = 1.0) -> None:
        self._pgid = pgid
        self._proc_root = proc_root
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = datetime.now(UTC)
        self._sample_count = 0
        self._io_read: int | None = None
        self._io_write: int | None = None
        self._fd_peak: int | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pg-resource-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> CommandResourceSample:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 2)
        return CommandResourceSample(
            started_at=self._started_at,
            ended_at=datetime.now(UTC),
            sample_count=self._sample_count,
            io_read_bytes=self._io_read,
            io_write_bytes=self._io_write,
            fd_peak=self._fd_peak,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample_once()
            except Exception:
                logger.debug("process-group sample failed", exc_info=True)
            if self._stop.wait(self._interval):
                return

    def _sample_once(self) -> None:
        read_total = 0
        write_total = 0
        fd_total = 0
        saw_io = False
        saw_fd = False
        for entry in self._proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            if _pgid_of(entry / "stat") != self._pgid:
                continue
            try:
                fd_total += len(list((entry / "fd").iterdir()))
                saw_fd = True
            except OSError:
                pass
            try:
                for line in (entry / "io").read_text().splitlines():
                    if line.startswith("read_bytes:"):
                        read_total += int(line.split()[1])
                        saw_io = True
                    elif line.startswith("write_bytes:"):
                        write_total += int(line.split()[1])
            except OSError:
                pass
        if not (saw_io or saw_fd):
            return
        self._sample_count += 1
        if saw_io:
            self._io_read = max(self._io_read or 0, read_total)
            self._io_write = max(self._io_write or 0, write_total)
        if saw_fd:
            self._fd_peak = max(self._fd_peak or 0, fd_total)
```

- [ ] **Step 4: 挂进 `_run_posix_command`**

在 `local_sandbox.py` 里取得 `process_group_id`(594 行附近)之后:

```python
        resource_sampler = None
        if process_group_id is not None and telemetry.per_command_sampling_enabled():
            try:
                resource_sampler = telemetry.ProcessGroupSampler(process_group_id)
                resource_sampler.start()
            except Exception:
                resource_sampler = None
```

在该函数已有的收尾/`finally` 路径中(进程 wait 完成后):

```python
        if resource_sampler is not None:
            try:
                telemetry.publish_command_sample(resource_sampler.stop())
            except Exception:
                logger.debug("command resource sample publish failed", exc_info=True)
```

import 用模块形式 `from deerflow.sandbox import telemetry`(保持 sandbox 层无 ansich import)。

- [ ] **Step 5: 跑测试通过;Step 6: `PYTHONPATH=. uv run pytest tests/test_harness_boundary.py -v` 确认边界不破;Step 7: Commit**

```bash
git add backend/packages/harness/deerflow/sandbox/telemetry.py backend/packages/harness/deerflow/sandbox/local/local_sandbox.py backend/tests/test_local_sandbox_telemetry.py
git commit -m "feat(sandbox): ansich-free per-command process-group resource sampler"
```

---

### Task 4: 环境读数函数与 provider peek API

**Files:**
- Create: `backend/packages/harness/deerflow/ansich/probes/env_samplers.py`
- Modify: `backend/packages/harness/deerflow/sandbox/sandbox_provider.py`(基类加 `peek_thread_sandbox`)
- Modify: `backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py`
- Modify: `backend/packages/harness/deerflow/community/aio_sandbox/`(provider 覆写)
- Test: `backend/tests/ansich/test_env_samplers.py`

**Interfaces:**
- Consumes: Task 1 的指标名约定。
- Produces:
  - `EnvironmentReading(environment_scope: str, metrics: dict[str, dict[str, int | None]])`(`metrics[name] = {"value": int, "limit": int|None}`,与 payload 的 metric 结构逐字段对应)
  - `sample_local_host(workspace_path: Path, *, proc_root: Path = Path("/proc")) -> EnvironmentReading`
  - `resolve_container_cgroup_dir(container_id: str, *, cgroup_root: Path = Path("/sys/fs/cgroup")) -> Path | None`
  - `sample_aio_container(cgroup_dir: Path, *, proc_root: Path = Path("/proc")) -> EnvironmentReading | None`
  - `SandboxProvider.peek_thread_sandbox(user_id: str | None, thread_id: str) -> Sandbox | None`(默认 None;仅内存查找,禁止 store/backend 往返)

- [ ] **Step 1: 写失败测试**(全部用注入的假目录,不依赖真容器)

```python
from pathlib import Path

from deerflow.ansich.probes.env_samplers import (
    EnvironmentReading,
    resolve_container_cgroup_dir,
    sample_aio_container,
    sample_local_host,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_sample_local_host_disk_and_psi(tmp_path):
    proc = tmp_path / "proc"
    _write(proc / "pressure" / "io", "some avg10=12.34 avg60=1.00 avg300=0.10 total=1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
    _write(proc / "pressure" / "memory", "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
    reading = sample_local_host(tmp_path, proc_root=proc)
    assert reading.environment_scope == "host_shared"
    disk = reading.metrics["disk_free_bytes"]
    assert disk["value"] > 0 and disk["limit"] >= disk["value"]
    assert reading.metrics["psi_io_some_avg10_milli"]["value"] == 12340


def test_sample_local_host_without_psi_omits_metric(tmp_path):
    reading = sample_local_host(tmp_path, proc_root=tmp_path / "no-proc")
    assert "psi_io_some_avg10_milli" not in reading.metrics
    assert "disk_free_bytes" in reading.metrics


def test_resolve_container_cgroup_dir(tmp_path):
    cid = "abc123"
    scope = tmp_path / "system.slice" / f"docker-{cid}.scope"
    scope.mkdir(parents=True)
    assert resolve_container_cgroup_dir(cid, cgroup_root=tmp_path) == scope
    assert resolve_container_cgroup_dir("missing", cgroup_root=tmp_path) is None


def test_sample_aio_container_reads_cgroup_and_proc(tmp_path):
    cgroup = tmp_path / "cg"
    proc = tmp_path / "proc"
    _write(cgroup / "cgroup.procs", "101\n")
    _write(cgroup / "io.stat", "8:0 rbytes=1000 wbytes=2000 rios=1 wios=2\n")
    _write(cgroup / "memory.current", "4096\n")
    _write(proc / "101" / "stat", "101 (x) S 1 101 101 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 0 0 0\n")
    (proc / "101" / "fd").mkdir(parents=True)
    (proc / "101" / "fd" / "0").write_text("")
    _write(proc / "101" / "limits", "Max open files            1024                 4096                 files\n")
    reading = sample_aio_container(cgroup, proc_root=proc)
    assert reading.environment_scope == "container"
    assert reading.metrics["fd_open"] == {"value": 1, "limit": 1024}
    assert reading.metrics["io_read_bytes"]["value"] == 1000
    assert reading.metrics["io_write_bytes"]["value"] == 2000
    assert reading.metrics["rss_bytes"]["value"] == 4096


def test_sample_aio_container_missing_cgroup_files_omit_metrics(tmp_path):
    cgroup = tmp_path / "cg"
    _write(cgroup / "cgroup.procs", "")
    reading = sample_aio_container(cgroup, proc_root=tmp_path / "proc")
    assert reading is None  # 什么都没读到 → 不发样本,不猜


def test_local_provider_peek(tmp_path):
    from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider

    provider = LocalSandboxProvider(base_dir=str(tmp_path))
    assert provider.peek_thread_sandbox(None, "t-1") is not None


def test_base_provider_peek_defaults_to_none():
    from deerflow.sandbox.sandbox_provider import SandboxProvider

    class Dummy(SandboxProvider):
        def acquire(self, thread_id=None):  # pragma: no cover
            raise NotImplementedError

        def get(self, sandbox_id):  # pragma: no cover
            return None

        def release(self, sandbox_id):  # pragma: no cover
            pass

    assert Dummy().peek_thread_sandbox(None, "t") is None
```

注:`SandboxProvider` 的抽象方法集合以实际基类为准,先
`grep -n "def \|abstractmethod" backend/packages/harness/deerflow/sandbox/sandbox_provider.py | head -30`,
Dummy 按需补齐抽象方法。`LocalSandboxProvider` 构造同 Task 3 的注意事项。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 `env_samplers.py`**

```python
"""Honest OS-level environment readings for the Ansich environment probe.

Every function reads best-effort and OMITS a metric it cannot read — a
missing dimension is never written as zero (usage 的"未报告≠0"纪律).
All functions are blocking filesystem readers; callers must offload via
asyncio.to_thread.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_PSI_SOME_AVG10 = re.compile(r"^some avg10=(\d+(?:\.\d+)?)", re.MULTILINE)


@dataclass(frozen=True)
class EnvironmentReading:
    environment_scope: str
    metrics: dict[str, dict[str, int | None]]


def _psi_milli(pressure_file: Path) -> int | None:
    try:
        match = _PSI_SOME_AVG10.search(pressure_file.read_text())
    except OSError:
        return None
    return int(float(match.group(1)) * 1000) if match else None


def sample_local_host(workspace_path: Path, *, proc_root: Path = Path("/proc")) -> EnvironmentReading:
    metrics: dict[str, dict[str, int | None]] = {}
    try:
        usage = shutil.disk_usage(workspace_path)
        metrics["disk_free_bytes"] = {"value": usage.free, "limit": usage.total}
    except OSError:
        pass
    for name, filename in (("psi_io_some_avg10_milli", "io"), ("psi_memory_some_avg10_milli", "memory")):
        value = _psi_milli(proc_root / "pressure" / filename)
        if value is not None:
            metrics[name] = {"value": value, "limit": None}
    return EnvironmentReading(environment_scope="host_shared", metrics=metrics)


def resolve_container_cgroup_dir(container_id: str, *, cgroup_root: Path = Path("/sys/fs/cgroup")) -> Path | None:
    for candidate in (
        cgroup_root / "system.slice" / f"docker-{container_id}.scope",
        cgroup_root / "docker" / container_id,
    ):
        if candidate.is_dir():
            return candidate
    return None


def _soft_open_files_limit(proc_root: Path, pid: str) -> int | None:
    try:
        for line in (proc_root / pid / "limits").read_text().splitlines():
            if line.startswith("Max open files"):
                fields = line.split()
                return int(fields[3])
    except (OSError, IndexError, ValueError):
        return None
    return None


def sample_aio_container(cgroup_dir: Path, *, proc_root: Path = Path("/proc")) -> EnvironmentReading | None:
    metrics: dict[str, dict[str, int | None]] = {}
    pids: list[str] = []
    try:
        pids = [line for line in (cgroup_dir / "cgroup.procs").read_text().split() if line.isdigit()]
    except OSError:
        pass
    if pids:
        fd_total = 0
        saw_fd = False
        for pid in pids:
            try:
                fd_total += len(list((proc_root / pid / "fd").iterdir()))
                saw_fd = True
            except OSError:
                continue
        if saw_fd:
            metrics["fd_open"] = {"value": fd_total, "limit": _soft_open_files_limit(proc_root, pids[0])}
    try:
        read_total = 0
        write_total = 0
        for line in (cgroup_dir / "io.stat").read_text().splitlines():
            for field in line.split()[1:]:
                if field.startswith("rbytes="):
                    read_total += int(field.removeprefix("rbytes="))
                elif field.startswith("wbytes="):
                    write_total += int(field.removeprefix("wbytes="))
        metrics["io_read_bytes"] = {"value": read_total, "limit": None}
        metrics["io_write_bytes"] = {"value": write_total, "limit": None}
    except OSError:
        pass
    try:
        metrics["rss_bytes"] = {"value": int((cgroup_dir / "memory.current").read_text().strip()), "limit": None}
    except (OSError, ValueError):
        pass
    if not metrics:
        return None
    return EnvironmentReading(environment_scope="container", metrics=metrics)
```

- [ ] **Step 4: provider peek API**

基类 `sandbox_provider.py`:

```python
    def peek_thread_sandbox(self, user_id: str | None, thread_id: str) -> "Sandbox | None":
        """In-memory-only lookup of the thread's sandbox; never touches a store/backend.

        Default None: providers without a cheap in-memory answer stay honest
        (the environment probe then records uninstrumented coverage).
        """
        return None
```

`LocalSandboxProvider` 覆写:`return self.acquire(thread_id)`(local acquire 只建目录、进 LRU,幂等且廉价)。

`AioSandboxProvider` 覆写:**只查内存映射**。先执行
`grep -n "_sandboxes\|container_name\|def _container_name\|def get(" backend/packages/harness/deerflow/community/aio_sandbox/provider*.py | head -20`
找到 (a) 活跃沙箱映射属性名,(b) user/thread → 容器名的既有命名助手;实现为:遍历活跃映射,返回 `SandboxInfo` 的容器名与该命名助手输出一致的沙箱,否则 None。加锁读取时必须使用 provider 已有的 `self._lock` 惯例;禁止调用 ownership store 或 docker backend(会阻塞事件循环——该方法会被 `get()` 同级的路径引用,参见 `tests/blocking_io/test_aio_sandbox_get.py` 的既有约束)。

- [ ] **Step 5: 跑测试通过;Step 6: Commit**

```bash
git add backend/packages/harness/deerflow/ansich/probes/env_samplers.py backend/packages/harness/deerflow/sandbox/sandbox_provider.py backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py backend/packages/harness/deerflow/community/aio_sandbox/ backend/tests/ansich/test_env_samplers.py
git commit -m "feat(ansich): environment readers (host/container) and provider peek API"
```

---

### Task 5: `AnsichEnvironmentProbe` + worker 接线 + blocking-io 锚点

**Files:**
- Create: `backend/packages/harness/deerflow/ansich/probes/environment.py`
- Modify: `backend/packages/harness/deerflow/ansich/probes/__init__.py`(导出)
- Modify: `backend/packages/harness/deerflow/runtime/runs/worker.py`(heartbeat 启动块之后,~401 行;停止点 ~785 行)
- Modify: `backend/app/gateway/app.py` 或 ansich 装配点(打开 per-command 开关;先 `grep -rn "create_sql_ansich_service\|ansich_service" backend/app/gateway/app.py | head` 定位装配处)
- Test: `backend/tests/ansich/test_environment_probe.py`、`backend/tests/blocking_io/test_environment_probe.py`

**Interfaces:**
- Consumes: Task 1 builders、Task 2 config、Task 4 readers/peek。
- Produces:
  - `ScopeDecl(scope_kind: str, external_ref: str, relation_role: str)`
  - `ProbeResolution(scopes: tuple[ScopeDecl, ...], coverage: str, provider: str, reading_scope: ScopeDecl | None, reading: EnvironmentReading | None)`
  - `AnsichEnvironmentProbe(service, *, task_id, run_id, interval_seconds, is_owner, resolve: Callable[[], ProbeResolution | None])`,`start()` / `stop()`
  - `build_environment_resolver(app_config, *, user_id, thread_id) -> Callable[[], ProbeResolution | None]`(worker 调用;内部做 provider 分派)

- [ ] **Step 1: 写失败测试**(fake service 收集 record 的 envelope;fake resolver 注入)

```python
import asyncio
from datetime import UTC, datetime

import pytest

from deerflow.ansich.probes.env_samplers import EnvironmentReading
from deerflow.ansich.probes.environment import AnsichEnvironmentProbe, ProbeResolution, ScopeDecl


class FakeService:
    def __init__(self):
        self.recorded = []

    def record(self, envelope):
        self.recorded.append(envelope)


def _container_resolution():
    decl = ScopeDecl("sandbox", "aio:thread-1", "sandbox_boundary")
    return ProbeResolution(
        scopes=(decl,),
        coverage="continuous",
        provider="aio",
        reading_scope=decl,
        reading=EnvironmentReading("container", {"fd_open": {"value": 10, "limit": 100}}),
    )


async def _run_probe(resolution, ticks=2, is_owner=lambda: True):
    service = FakeService()
    probe = AnsichEnvironmentProbe(
        service,
        task_id="6f000000-0000-4000-8000-000000000001",
        run_id="run-1",
        interval_seconds=0.05,
        is_owner=is_owner,
        resolve=lambda: resolution,
    )
    probe.start()
    await asyncio.sleep(0.05 * (ticks + 1.5))
    await probe.stop()
    return service.recorded


@pytest.mark.asyncio
async def test_probe_emits_scope_once_then_samples():
    recorded = await _run_probe(_container_resolution(), ticks=3)
    scope_obs = [o for o in recorded if o.kind == "scope.snapshotted"]
    samples = [o for o in recorded if o.kind == "environment.sampled"]
    assert len(scope_obs) == 1
    assert len(samples) >= 2
    assert samples[0].payload["coverage"] == "continuous"
    assert samples[0].payload["environment_scope"] == "container"


@pytest.mark.asyncio
async def test_probe_uninstrumented_declares_once_and_stops():
    decl = ScopeDecl("sandbox", "e2b:thread-1", "sandbox_boundary")
    resolution = ProbeResolution(scopes=(decl,), coverage="uninstrumented", provider="e2b", reading_scope=decl, reading=None)
    recorded = await _run_probe(resolution, ticks=4)
    samples = [o for o in recorded if o.kind == "environment.sampled"]
    assert len(samples) == 1
    assert samples[0].payload["coverage"] == "uninstrumented"
    assert samples[0].payload["metrics"] == {}


@pytest.mark.asyncio
async def test_probe_skips_tick_when_resolver_returns_none():
    recorded = await _run_probe(None, ticks=2)
    assert recorded == []


@pytest.mark.asyncio
async def test_probe_stops_on_ownership_loss():
    recorded = await _run_probe(_container_resolution(), ticks=4, is_owner=lambda: False)
    assert recorded == []


@pytest.mark.asyncio
async def test_probe_fail_open_on_resolver_exception():
    def boom():
        raise RuntimeError("sampler exploded")

    service = FakeService()
    probe = AnsichEnvironmentProbe(
        service, task_id="6f000000-0000-4000-8000-000000000001", run_id="r",
        interval_seconds=0.05, is_owner=lambda: True, resolve=boom,
    )
    probe.start()
    await asyncio.sleep(0.2)
    await probe.stop()  # 不抛异常即通过
```

blocking-io 锚点 `backend/tests/blocking_io/test_environment_probe.py`(照抄该目录现有锚点的结构,例如 `test_jsonl_run_event_store.py` 的骨架):resolver 里执行一次真实文件读(`Path("/proc/self/stat").read_text()`,无 `/proc` 时 `tmp_path` 文件),在 Blockbuster 门内跑一个 tick,断言不触发 `BlockingError`——锁定"resolve 经 `asyncio.to_thread` 下放"。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 probe**

`environment.py` 骨架完全照抄 `task_heartbeat.py`(模块级 `_PRODUCER_INSTANCE_ID`/`_PRODUCER_SEQUENCE`、`start/stop/_run` 循环、ownership 检查、日志措辞),差异在 tick 体:

```python
    async def _record_tick(self) -> None:
        try:
            resolution = await asyncio.to_thread(self._resolve)
        except Exception:
            logger.warning("Ansich environment sampling failed for run %s", self._run_id, exc_info=True)
            return
        if resolution is None:
            return
        try:
            now = datetime.now(UTC)
            for decl in resolution.scopes:
                key = (decl.scope_kind, decl.external_ref)
                if key in self._declared_scopes:
                    continue
                self._service.record(
                    ObservationEnvelope.scope_snapshotted(
                        task_id=self._task_id, run_id=self._run_id, occurred_at=now,
                        scope_kind=decl.scope_kind, external_ref=decl.external_ref,
                        relation_role=decl.relation_role,
                        source_event_id=f"run:{self._run_id}:env-scope:{decl.scope_kind}:{decl.external_ref}",
                        producer_seq=_next_producer_sequence(),
                        producer_name="deerflow-environment-probe", producer_version="1",
                        producer_instance_id=_PRODUCER_INSTANCE_ID,
                    )
                )
                self._declared_scopes.add(key)
            if resolution.coverage == "uninstrumented":
                if not self._declaration_sent:
                    self._emit_sample(resolution, now, sample_count=0, metrics={})
                    self._declaration_sent = True
                self._stop_event.set()  # 声明一次后循环无事可做
                return
            if resolution.reading is None:
                return  # 沙箱尚未就绪:显式覆盖空洞,不猜
            self._tick += 1
            self._emit_sample(resolution, now, sample_count=1, metrics=resolution.reading.metrics)
            self._last_tick_at = now
        except Exception:
            logger.warning("Ansich environment observation failed for run %s", self._run_id, exc_info=True)
```

`_emit_sample` 组装 payload(`window.started_at` = 上一 tick 时间或 probe 启动时间)并用 `ObservationEnvelope.environment_sampled` 发射,`scope_id = scope_entity_id(kind, scope_reference_hash(kind, ref))`,`source_event_id = f"run:{run_id}:env:{scope_id}:{tick}"`(uninstrumented 用 `:decl`)。

`build_environment_resolver(app_config, *, user_id, thread_id)`(同文件):
- 读 `app_config.sandbox` 判定 provider 种类(先 `grep -n "sandbox" backend/packages/harness/deerflow/config/app_config.py | head` 找 provider 类路径字段;用类路径字符串包含 `LocalSandboxProvider` / `AioSandboxProvider` 判定,匹配现有 `is_local_sandbox` 风格)。
- **local**:scopes = `(ScopeDecl("host", <hostname>, "host_environment"), ScopeDecl("sandbox", f"local:{thread_id}", "sandbox_boundary"))`;reading = `sample_local_host(workspace_dir)`,reading_scope = host 那个 decl。workspace 目录:worker 里已有 thread 数据目录构造惯例——先 `grep -rn "user-data" backend/packages/harness/deerflow/agents/middlewares/thread_data*.py | head` 找路径助手并复用;找不到独立助手就按 `ThreadDataMiddleware` 的构造复制路径拼接(`users/{user_id}/threads/{thread_id}/user-data/workspace`)。
- **AIO**:`provider = get_sandbox_provider()`;`sandbox = provider.peek_thread_sandbox(user_id, thread_id)`;None → 返回 `ProbeResolution(scopes=(), ..., reading=None, coverage="continuous")`(本 tick 跳过);有沙箱 → 从其 `SandboxInfo.container_id` 解析 cgroup(`resolve_container_cgroup_dir`),读 `sample_aio_container`;cgroup 不可得(远端 docker/cgroup v1)→ 降级为 uninstrumented 声明(scopes 含 sandbox decl)。
- **其他 provider**:uninstrumented,scope ref = `f"{provider 类名小写}:{thread_id}"`。

- [ ] **Step 4: worker 接线**

`worker.py` heartbeat 块(~401 行)之后,同样的守卫条件下:

```python
                if getattr(ansich_config, "environment_probe_enabled", False):
                    try:
                        from deerflow.ansich.probes.environment import AnsichEnvironmentProbe, build_environment_resolver

                        ansich_environment_probe = AnsichEnvironmentProbe(
                            ctx.ansich_service,
                            task_id=ansich_task.task_id,
                            run_id=run_id,
                            interval_seconds=float(ansich_config.effective_environment_sample_interval_seconds),
                            is_owner=lambda: record.owner_worker_id == worker_id,
                            resolve=build_environment_resolver(ctx.app_config, user_id=get_effective_user_id(), thread_id=thread_id),
                        )
                        ansich_environment_probe.start()
                    except Exception:
                        logger.warning("Run %s: could not start Ansich environment probe", run_id, exc_info=True)
```

变量声明与停止点与 `ansich_heartbeat` 完全对称(309 行附近声明 `ansich_environment_probe: Any | None = None`;785 行附近 `await ansich_environment_probe.stop()`,在 terminal 观测之前)。

Gateway 装配点(ansich service 创建处)加:

```python
        from deerflow.sandbox import telemetry as sandbox_telemetry

        sandbox_telemetry.set_per_command_sampling_enabled(
            ansich_config.enabled and ansich_config.environment_probe_enabled and ansich_config.environment_per_command_sampling
        )
```

- [ ] **Step 5: 跑测试(probe 单测 + blocking-io 锚点)通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ansich/test_environment_probe.py tests/blocking_io/test_environment_probe.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/packages/harness/deerflow/ansich/probes/ backend/packages/harness/deerflow/runtime/runs/worker.py backend/app/gateway/app.py backend/tests/ansich/test_environment_probe.py backend/tests/blocking_io/test_environment_probe.py
git commit -m "feat(ansich): environment probe with provider-dispatched sampling and worker wiring"
```

---

### Task 6: per_command 观测发射(tool probe 链)

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/tool_middleware.py`(`wrap_tool_call`/`awrap_tool_call` 的 raw 终态记录之后,841/886 行附近)
- Test: `backend/tests/ansich/test_tool_env_sample_emission.py`

**Interfaces:**
- Consumes: `deerflow.sandbox.telemetry.consume_command_sample()`(Task 3)、`ObservationEnvelope.environment_sampled`(Task 1)。
- Produces: bash ToolCall 的 `environment.sampled` 观测,`payload.tool_call_id` = Ansich ToolCall id,subject = sandbox Scope(`local:{thread_id}`)。

- [ ] **Step 1: 定位上下文(inspection)**

执行:
`grep -n "thread_id\|tool_name\|invocation\.\|_record_raw_result" backend/packages/harness/deerflow/ansich/tool_middleware.py | sed -n '1,40p'`
确认:(a) raw 终态记录点上下文里可拿到 Ansich `tool_call_id`、`task_id`、`run_id`、工具名;(b) thread_id 的获取方式(该文件或 `execution.py` 的运行上下文)。验收:能写出从该点取到四个值的表达式。

- [ ] **Step 2: 写失败测试**

用该文件现有测试(`grep -rl tool_middleware backend/tests | head -3`)的既有夹具驱动一次 bash 工具的 raw 成功路径,事先 `telemetry.publish_command_sample(...)` 放入一个样本,断言:
- service 收到一条 `environment.sampled`,`coverage == "per_command"`、`environment_scope == "process_group"`、`tool_call_id` 等于该调用的 Ansich ToolCall id;
- metrics 只含样本里非 None 的维度(`io_read_bytes`/`io_write_bytes`/`fd_peak` → `fd_open`);
- 非 bash 工具与空 ContextVar 时不发射;
- 发射路径抛异常不影响工具结果(fail-open:mock service.record 抛错,断言 ToolMessage 正常)。

- [ ] **Step 3: 实现**

在 `wrap_tool_call` 与 `awrap_tool_call` 中 `terminal_kind="tool.returned_raw"` 的 `_record_raw_result(...)` 调用之后追加(两处同样代码,提成模块级 helper `_emit_command_environment_sample(...)`):

```python
def _emit_command_environment_sample(*, service, task_id, run_id, tool_name, tool_call_id, thread_id) -> None:
    if tool_name != "bash" or thread_id is None:
        return
    try:
        from deerflow.sandbox.telemetry import consume_command_sample

        sample = consume_command_sample()
        if sample is None:
            return
        from ansich.safety import scope_entity_id, scope_reference_hash

        ref_hash = scope_reference_hash("sandbox", f"local:{thread_id}")
        metrics: dict[str, object] = {}
        if sample.fd_peak is not None:
            metrics["fd_open"] = {"value": sample.fd_peak, "limit": None}
        if sample.io_read_bytes is not None:
            metrics["io_read_bytes"] = {"value": sample.io_read_bytes, "limit": None}
        if sample.io_write_bytes is not None:
            metrics["io_write_bytes"] = {"value": sample.io_write_bytes, "limit": None}
        if not metrics:
            return
        service.record(
            ObservationEnvelope.environment_sampled(
                task_id=task_id,
                run_id=run_id,
                occurred_at=sample.ended_at,
                scope_id=scope_entity_id("sandbox", ref_hash),
                payload={
                    "environment_scope": "process_group",
                    "coverage": "per_command",
                    "window": {"started_at": sample.started_at, "ended_at": sample.ended_at, "sample_count": sample.sample_count},
                    "provider": "local",
                    "metrics": metrics,
                    "tool_call_id": tool_call_id,
                },
                source_event_id=f"tool:{tool_call_id}:env",
            )
        )
    except Exception:
        logger.debug("per-command environment sample emission failed", exc_info=True)
```

- [ ] **Step 4: 跑测试通过;Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/ansich/tool_middleware.py backend/tests/ansich/test_tool_env_sample_emission.py
git commit -m "feat(ansich): emit per-command environment samples from the tool probe chain"
```

---

### Task 7: 读模型表 + migration `0026_ansich_environment`

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/models.py`
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/0026_ansich_environment.py`
- Test: `backend/tests/ansich/test_environment_models.py`

**Interfaces:**
- Produces(Task 8/9/10 依赖的列名,逐字):
  - `AnsichEnvironmentCoverageRow`:`ansich_environment_coverage`,PK `(scope_id, environment_scope)`;列 `coverage: str`、`provider: str`、`as_of: datetime`、`last_obs_id: str`、`updated_at: datetime`
  - `AnsichEnvironmentStateRow`:`ansich_environment_state`,PK `(scope_id, environment_scope, metric)`;列 `latest_value: int`、`limit_value: int | None`、`as_of: datetime`、`window_started_at: datetime`、`window_min_value: int`、`sample_count: int`、`consecutive_growth_count: int`、`growth_started_at: datetime | None`、`last_obs_id: str`、`provider: str`、`updated_at: datetime`
  - `AnsichToolEnvSampleRow`:`ansich_tool_env_samples`,PK `tool_call_id: str`;列 `task_id: str`、`scope_id: str`、`io_read_bytes: int | None`、`io_write_bytes: int | None`、`fd_peak: int | None`、`sample_count: int`、`started_at`、`ended_at`、`obs_id: str`(全部普通 String(36)/BigInteger 列,**不设 FK**——per_command 行不做依赖等待,见 Task 8)
  - `AnsichAlertReadModelRow` 加列 `possibly_affected_task_ids: JSON | None`

- [ ] **Step 1: 写失败测试**(建内存 SQLite,`Base.metadata.create_all`,插入/读回三张表各一行;断言 AlertReadModel 新列可空写入)
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: models.py 定义三个 Row + 附加列**,`scope_id` 列对 coverage/state 两表加 FK `ansich_entities.entity_id, ondelete="CASCADE"`;索引:`ix_ansich_env_state_scope("scope_id")`、`ix_ansich_tool_env_samples_task("task_id")`。BigInteger 用于字节数列。
- [ ] **Step 4: migration**

```bash
cd backend && make migrate-rev MSG="ansich environment observability read models"
```

将生成文件重命名/改写为 `0026_ansich_environment.py`(`revision="0026_ansich_environment"`,`down_revision="0025_ansich_assessor_watermarks"`),照 `0016` 的 `_create_table`/`_create_index` 幂等风格改写;`possibly_affected_task_ids` 列用 `_helpers.safe_add_column`。`downgrade()` 按仓库既有 revision 的惯例处理(先看 0023-0025 的 downgrade 写法,保持一致)。

- [ ] **Step 5: 跑测试 + `PYTHONPATH=. uv run pytest tests/test_persistence_bootstrap.py -v`(迁移链健康)**
- [ ] **Step 6: Commit**

```bash
git add backend/packages/harness/deerflow/ansich/persistence/models.py backend/packages/harness/deerflow/persistence/migrations/versions/0026_ansich_environment.py backend/tests/ansich/test_environment_models.py
git commit -m "feat(ansich): environment read-model tables and migration 0026"
```

---### Task 8: `environment-projector@1`

**Files:**
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py`
- Test: `backend/tests/ansich/test_environment_projector.py`

**Interfaces:**
- Consumes: Task 1 payload 模型、Task 7 行模型。
- Produces: 投影行为(Task 9/10 读这些行);`_GROWTH_TRACKED_METRICS = frozenset({"fd_open"})`。

- [ ] **Step 1: 写失败测试**(用 `create_sql_ansich_service` 起真 SQLite 服务,风格照抄 `tests/ansich/` 现有投影测试;记得该目录 conftest 已启 WAL)

用例(每个都经 `service.record(...)` + settle 等待,复用现有 `tests/support/ansich_settle.py` 惯例):
1. `scope.snapshotted`(sandbox scope,含 relation_role)→ 再发 `environment.sampled`(continuous,fd_open=100/limit=1024)→ 断言 coverage 行与 state 行落库,`within_scope` 关系存在(直接查 `AnsichRelationRow`)。
2. 三个递增 fd 样本(100→110→120)→ `consecutive_growth_count == 2`,`window_min_value == 100`,`growth_started_at` 等于第二个样本的 `occurred_at`;随后一个 90 → growth 归零、`growth_started_at is None`。
3. 同一 obs 重复投递(相同 `source_event_id` 由 collector 幂等吸收;直接二次调用投影函数或 `rebuild_projections()` 重放)→ state 行数值不变、`sample_count` 不翻倍。
4. scope 实体缺失时投影 job 进 dependency-pending 而非失败(先发 `environment.sampled` 不发 scope;断言 job 未 failed;补发 `scope.snapshotted` 后收敛)。
5. per_command 样本 → `ansich_tool_env_samples` 一行,重复投递幂等;不产生 state 行的 growth 变化。
6. uninstrumented 声明 → 仅 coverage 行(coverage="uninstrumented"),无 state 行。
7. `rebuild_projections()` 后重放收敛到相同行内容(replay 纪律)。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 注册与分派**

sql.py 三处:
1. `_PROJECTORS` 元组(284 行)在 `("task-safety", "1")` 之后、`evaluation-projector` 之前插入 `("environment-projector", "1")`(环境投影依赖 task-safety 先建 scope 实体;注册顺序即同一 observation 的执行优先级)。
2. `_PROJECTOR_KINDS` 加 `"environment-projector": frozenset({"environment.sampled"})`。
3. claim 分派链(898-915 行)加 `elif projector_name == "environment-projector": await self._project_environment(session, observation)`。

- [ ] **Step 4: 实现 `_project_environment`**

```python
    _GROWTH_TRACKED_METRICS = frozenset({"fd_open"})

    async def _project_environment(self, session: AsyncSession, observation: ObservationEnvelope) -> None:
        from ansich.environment import EnvironmentSamplePayload

        payload = EnvironmentSamplePayload.model_validate(observation.payload, strict=False)
        scope_id = observation.subject_id
        if await session.get(AnsichEntityRow, scope_id) is None:
            raise _ProjectionDependencyPending(f"environment sample {observation.obs_id} is waiting for Scope {scope_id}")

        coverage = await session.get(
            AnsichEnvironmentCoverageRow, (scope_id, payload.environment_scope), with_for_update=True
        )
        if coverage is None:
            session.add(
                AnsichEnvironmentCoverageRow(
                    scope_id=scope_id, environment_scope=payload.environment_scope,
                    coverage=payload.coverage, provider=payload.provider,
                    as_of=observation.occurred_at, last_obs_id=observation.obs_id,
                    updated_at=observation.recorded_at,
                )
            )
        elif coverage.last_obs_id != observation.obs_id and observation.occurred_at >= coverage.as_of:
            coverage.coverage = payload.coverage
            coverage.provider = payload.provider
            coverage.as_of = observation.occurred_at
            coverage.last_obs_id = observation.obs_id
            coverage.updated_at = observation.recorded_at

        if payload.coverage == "per_command":
            existing = await session.get(AnsichToolEnvSampleRow, payload.tool_call_id)
            if existing is None:
                metrics = payload.metrics
                session.add(
                    AnsichToolEnvSampleRow(
                        tool_call_id=payload.tool_call_id, task_id=observation.task_id, scope_id=scope_id,
                        io_read_bytes=(metrics["io_read_bytes"].value if "io_read_bytes" in metrics else None),
                        io_write_bytes=(metrics["io_write_bytes"].value if "io_write_bytes" in metrics else None),
                        fd_peak=(metrics["fd_open"].value if "fd_open" in metrics else None),
                        sample_count=payload.window.sample_count,
                        started_at=payload.window.started_at, ended_at=payload.window.ended_at,
                        obs_id=observation.obs_id,
                    )
                )
            return  # per_command 不驱动 state 行的趋势字段

        if payload.coverage == "uninstrumented":
            return

        for metric, value in payload.metrics.items():
            # 先锁后读:兄弟 Task 的并发投影可能落在同一 scope 行上,
            # 与 _upsert_high_water_contribution 同一纪律。
            row = await session.get(
                AnsichEnvironmentStateRow, (scope_id, payload.environment_scope, metric), with_for_update=True
            )
            if row is None:
                session.add(
                    AnsichEnvironmentStateRow(
                        scope_id=scope_id, environment_scope=payload.environment_scope, metric=metric,
                        latest_value=value.value, limit_value=value.limit,
                        as_of=observation.occurred_at, window_started_at=payload.window.started_at,
                        window_min_value=value.value, sample_count=payload.window.sample_count,
                        consecutive_growth_count=0, growth_started_at=None,
                        last_obs_id=observation.obs_id, provider=payload.provider,
                        updated_at=observation.recorded_at,
                    )
                )
                continue
            if row.last_obs_id == observation.obs_id or observation.occurred_at < row.as_of:
                continue  # 重复投递 / 迟到样本:no-op,重放确定性
            if metric in self._GROWTH_TRACKED_METRICS and value.value > row.latest_value:
                if row.consecutive_growth_count == 0:
                    row.growth_started_at = observation.occurred_at
                row.consecutive_growth_count += 1
            else:
                row.consecutive_growth_count = 0
                row.growth_started_at = None
            row.window_min_value = min(row.window_min_value, value.value)
            row.latest_value = value.value
            row.limit_value = value.limit
            row.as_of = observation.occurred_at
            row.sample_count += payload.window.sample_count
            row.last_obs_id = observation.obs_id
            row.provider = payload.provider
            row.updated_at = observation.recorded_at
```

同时确认 `rebuild_projections()` 的清表列表包含三张新表(grep `rebuild_projections` 找到删除集合,追加)。

- [ ] **Step 5: 跑测试通过;Step 6: 跑 `tests/ansich/` 全量回归;Step 7: Commit**

```bash
git add backend/packages/harness/deerflow/ansich/persistence/sql.py backend/tests/ansich/test_environment_projector.py
git commit -m "feat(ansich): environment-projector@1 with locked current-state rows"
```

---

### Task 9: `environment-pressure@1` assessor + Alert 类型与周期评估

**Files:**
- Modify: `backend/packages/ansich/ansich/environment.py`(纯评估函数)
- Modify: `backend/packages/ansich/ansich/alerts/episodes.py`(AlertType + 条件分支)
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py`(`assess_operations` 尾部接入 `_assess_environment`;构造参数)
- Modify: `create_sql_ansich_service` 装配(先 `grep -rn "def create_sql_ansich_service" backend/packages/harness/deerflow/ansich/ | head -2` 定位;把 interval 与阈值从 `AnsichConfig` 传入,镜像 `heartbeat_stale_after_seconds` 的传递方式)
- Test: `backend/tests/ansich/test_environment_assessor.py`(纯函数)、`backend/tests/ansich/test_environment_alerts.py`(端到端 episode)

**Interfaces:**
- Produces:
  - `ansich.environment.EnvironmentThresholds`(字段与 Task 2 的 9 个阈值一一对应,同名去 `environment_` 前缀:`fd_warn_ratio` 等)
  - `assess_environment_pressure(*, scope_id, metric, environment_scope, coverage, latest_value, limit, as_of, last_obs_id, now, sample_interval_seconds, thresholds) -> Assessment | None`(非规则指标返回 None)
  - `assess_environment_leak(*, scope_id, environment_scope, coverage, consecutive_growth_count, growth_started_at, window_min_value, latest_value, as_of, last_obs_id, now, thresholds) -> Assessment | None`
  - `AlertType` += `"environment_pressure"`, `"environment_leak_suspected"`
  - assertion `field_name`:`environment_pressure:{metric}` / `environment_leak:fd_open`;`value_json` 仅稳定字段 `{"value", "metric", "environment_scope", "coverage"}`

- [ ] **Step 1: 写纯函数失败测试**(`test_environment_assessor.py`)

关键断言(每条独立用例):
- fd 100/1024 → ok;850/1024 → warning;990/1024 → critical;limit=None → unknown。
- `coverage="uninstrumented"` → unknown;`now - as_of > 3×interval`(continuous)→ unknown。
- `disk_free_bytes` free/total 比 0.08 → warning、0.03 → critical(方向相反于 fd)。
- `psi_io_some_avg10_milli` 50000 → warning、90000 → critical。
- `io_read_bytes` → 返回 None(v1 无压力规则的指标不产断言)。
- 泄漏:growth=6、span 70s、净增 60、environment_scope="container"、coverage="continuous" → suspected;`process_group` 或 `host_shared` 输入 → **返回 None**(spec 强制执行点);growth=5 → none;数据过期 → unknown。
- `Assessment.value` 不含 `latest_value`、不含 task ids(仅稳定类别字段——锁定"仅跃迁追加"前提)。
- `config_hash` 等于 `canonical_config_hash(thresholds.model_dump())`。

- [ ] **Step 2: 实现纯函数**(`assessor NamedVersion(name="environment-pressure", version="1")`;`authority_class="configured_rule"`、`fidelity_class="rule"`;evidence = `(EvidenceRef(obs_id=last_obs_id),)`,unknown 且无样本时为空)

规则表实现为模块常量,避免分支蔓延:

```python
def _pressure_state(metric: str, value: int, limit: int | None, t: EnvironmentThresholds) -> str | None:
    if metric == "fd_open":
        if limit is None or limit <= 0:
            return "unknown"
        ratio = value / limit
        return "critical" if ratio >= t.fd_critical_ratio else "warning" if ratio >= t.fd_warn_ratio else "ok"
    if metric == "disk_free_bytes":
        if limit is None or limit <= 0:
            return "unknown"
        ratio = value / limit
        return "critical" if ratio <= t.disk_free_critical_ratio else "warning" if ratio <= t.disk_free_warn_ratio else "ok"
    if metric in ("psi_io_some_avg10_milli", "psi_memory_some_avg10_milli"):
        return "critical" if value >= t.psi_critical_milli else "warning" if value >= t.psi_warn_milli else "ok"
    return None  # 无压力规则的指标
```

- [ ] **Step 3: episodes.py 扩展**

`AlertType` Literal 加两个值;`alert_conditions_from_assessment` 加两个分支(照 `_condition` 既有用法):

```python
    if assessment.field_name.startswith("environment_pressure:"):
        metric = assessment.field_name.split(":", 1)[1]
        severity: AlertSeverity = "critical" if value == "critical" else "warning"
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="environment_pressure",
                stable_condition_key=f"env:{metric}",
                active=value in {"warning", "critical"},
                severity=severity,
            ),
        )
    if assessment.field_name == "environment_leak:fd_open":
        return (
            _condition(
                assessment,
                source_assertion_id=source_assertion_id,
                alert_type="environment_leak_suspected",
                stable_condition_key="env-leak:fd_open",
                active=value == "suspected",
                severity="warning",
            ),
        )
```

- [ ] **Step 4: sql.py 周期评估**

`assess_operations`(4256 行)在 budget 段之后、read-model 刷新之前加 `changed += await self._assess_environment(session, asserted_at)`。实现:

```python
    _ENVIRONMENT_ALERT_TYPES = ("environment_pressure", "environment_leak_suspected")

    async def _assess_environment(self, session: AsyncSession, asserted_at: datetime) -> int:
        # 候选 scope:有 coverage 行且(挂着 running Task,或还有未 resolve 的环境 episode)。
        running_by_scope: dict[str, list[str]] = {}
        rows = await session.execute(
            select(AnsichRelationRow.object_id, AnsichRelationRow.subject_id)
            .join(AnsichTaskSummaryRow, AnsichTaskSummaryRow.task_id == AnsichRelationRow.subject_id)
            .where(
                AnsichRelationRow.predicate == "within_scope",
                AnsichRelationRow.relation_role.in_(("sandbox_boundary", "host_environment")),
                AnsichTaskSummaryRow.control_value == "running",
            )
        )
        for scope_id, task_id in rows:
            running_by_scope.setdefault(scope_id, []).append(task_id)
        open_alert_scopes = set(
            (await session.execute(
                select(AnsichAlertRow.subject_id).where(
                    AnsichAlertRow.alert_type.in_(self._ENVIRONMENT_ALERT_TYPES),
                    AnsichAlertRow.resolved_at.is_(None),
                )
            )).scalars()
        )
        candidate_scopes = set(running_by_scope) | open_alert_scopes
        if not candidate_scopes:
            return 0
        changed = 0
        state_rows = list((await session.execute(
            select(AnsichEnvironmentStateRow).where(AnsichEnvironmentStateRow.scope_id.in_(candidate_scopes))
        )).scalars())
        coverage_rows = {
            (row.scope_id, row.environment_scope): row
            for row in (await session.execute(
                select(AnsichEnvironmentCoverageRow).where(AnsichEnvironmentCoverageRow.scope_id.in_(candidate_scopes))
            )).scalars()
        }
        thresholds = self._environment_thresholds
        for row in state_rows:
            coverage = coverage_rows.get((row.scope_id, row.environment_scope))
            coverage_value = coverage.coverage if coverage is not None else "continuous"
            if coverage_value == "per_command":
                continue  # per_command 数据不进周期压力评估(读侧专用)
            assessment = assess_environment_pressure(
                scope_id=row.scope_id, metric=row.metric, environment_scope=row.environment_scope,
                coverage=coverage_value, latest_value=row.latest_value, limit=row.limit_value,
                as_of=_as_utc(row.as_of), last_obs_id=row.last_obs_id, now=asserted_at,
                sample_interval_seconds=self._environment_sample_interval_seconds, thresholds=thresholds,
            )
            if assessment is not None:
                changed += await self._persist_environment_assessment(session, assessment, asserted_at, running_by_scope.get(row.scope_id, []))
            if row.metric == "fd_open":
                leak = assess_environment_leak(
                    scope_id=row.scope_id, environment_scope=row.environment_scope, coverage=coverage_value,
                    consecutive_growth_count=row.consecutive_growth_count,
                    growth_started_at=(_as_utc(row.growth_started_at) if row.growth_started_at else None),
                    window_min_value=row.window_min_value, latest_value=row.latest_value,
                    as_of=_as_utc(row.as_of), last_obs_id=row.last_obs_id, now=asserted_at, thresholds=thresholds,
                )
                if leak is not None:
                    changed += await self._persist_environment_assessment(session, leak, asserted_at, running_by_scope.get(row.scope_id, []))
        # uninstrumented 声明也要产 unknown 断言(有 coverage 行、无 state 行的 scope)。
        for (scope_id, environment_scope), coverage in coverage_rows.items():
            if coverage.coverage != "uninstrumented":
                continue
            assessment = assess_environment_pressure(
                scope_id=scope_id, metric="fd_open", environment_scope=environment_scope,
                coverage="uninstrumented", latest_value=0, limit=None,
                as_of=_as_utc(coverage.as_of), last_obs_id=None, now=asserted_at,
                sample_interval_seconds=self._environment_sample_interval_seconds, thresholds=thresholds,
            )
            if assessment is not None:
                changed += await self._persist_environment_assessment(session, assessment, asserted_at, running_by_scope.get(scope_id, []))
        return changed
```

`_persist_environment_assessment` 完全镜像 heartbeat 断言持久化块(4300-4400 行的 unchanged-skip 结构),差异:
- `AnsichCurrentBeliefRow` 键为 `(assessment.subject_id, assessment.field_name)`;
- unchanged 比较用 `value_json == assessment.value`(value 已只含稳定字段);
- 之后调用 `self._reconcile_alerts_for_assessment(...)`(subject 为 scope 时 `AnsichTaskSummaryRow` get 为 None,终态跳过不生效——正确);
- reconcile 返回的变更里,若本次产生/更新了环境类型的 alert 行,把 `running_task_ids` 写入 `AnsichAlertReadModelRow.possibly_affected_task_ids`(找到 `_reconcile_alerts_for_assessment` 内部刷新 read-model 行的位置,给它加一个可选参数 `possibly_affected_task_ids: list[str] | None = None`,仅环境断言传值)。

构造参数:`SqlAnsichStore.__init__`(或等价 service 构造)加 `environment_sample_interval_seconds: int = 10` 与 `environment_thresholds: EnvironmentThresholds | None = None`(None → 默认值);`create_sql_ansich_service` 与 Gateway 装配从 `AnsichConfig` 传入(阈值映射:去 `environment_` 前缀逐字段构造 `EnvironmentThresholds`)。

- [ ] **Step 5: 写端到端 alert 测试**(`test_environment_alerts.py`;**测试用 `only_test_driven_assessments(service)` 关掉周期评估后自行驱动 `assess_operations(now=...)`**,遵守 F10-10 的测试纪律):
1. 注入 running Task + scope + fd 990/1024 状态 → `assess_operations` → `environment_pressure` episode open(severity critical);fd 回落 100 → 再评 → episode resolved;再次越阈 → episode 2(复发编号)。
2. fd 连续 6 个递增样本、净增 ≥50、span ≥60s → `environment_leak_suspected` open。
3. 样本停止 > 3×interval → belief 转 unknown、pressure condition inactive → episode resolve。
4. 断言仅跃迁追加:同状态连评三次,`ansich_belief_assertions` 行数不变。
5. `possibly_affected_task_ids` 落在 alert 读模型行,含 running task id。
6. Task 终态、无 open episode → scope 退出候选集(评估不再写行)。

- [ ] **Step 6: 全部通过后回归 `tests/ansich/`;Step 7: Commit**

```bash
git add backend/packages/ansich/ansich/environment.py backend/packages/ansich/ansich/alerts/episodes.py backend/packages/harness/deerflow/ansich/persistence/sql.py backend/tests/ansich/test_environment_assessor.py backend/tests/ansich/test_environment_alerts.py
git commit -m "feat(ansich): environment-pressure@1 assessor, leak rule, environment alert episodes"
```

---

### Task 10: Gateway API 读侧

**Files:**
- Modify: `backend/packages/ansich/ansich/environment.py`(view 模型)
- Modify: `backend/packages/ansich/ansich/service.py`(facade 方法)
- Modify: `backend/packages/harness/deerflow/ansich/persistence/sql.py`(backend 读方法)
- Modify: `backend/packages/harness/deerflow/ansich/__init__.py`(降级 stub 返回空视图)
- Modify: `backend/app/gateway/routers/ansich.py`(新路由 + alert filter Literal + ToolCall 详情附加字段)
- Test: `backend/tests/test_gateway_ansich_environment.py`(照抄该文件族现有 gateway ansich 测试的装配)

**Interfaces:**
- Produces:
  - `ansich.environment.EnvironmentMetricView(metric, latest_value, limit, as_of, sample_count, window_started_at, consecutive_growth_count)`
  - `ansich.environment.EnvironmentBeliefView(field_name, value: dict, as_of, asserted_at, source: NamedVersion, authority_class, fidelity_class, evidence_obs_ids: tuple[str, ...])`
  - `ansich.environment.EnvironmentAlertSummaryView(alert_id, alert_type, severity, workflow_state, opened_at, resolved_at)`
  - `ansich.environment.EnvironmentScopeView(scope_id, scope_kind, display_label, environment_scope, coverage, provider, metrics: tuple[EnvironmentMetricView, ...], beliefs: tuple[EnvironmentBeliefView, ...], alerts: tuple[EnvironmentAlertSummaryView, ...])`
  - `ansich.environment.TaskEnvironmentView(task_id, scopes: tuple[EnvironmentScopeView, ...])`
  - `AnsichService.get_task_environment(task_id: str) -> TaskEnvironmentView`
  - HTTP:`GET /api/ansich/tasks/{task_id}/environment`

- [ ] **Step 1: 写失败测试**

1. 端到端:probe 风格地 record scope + 样本 + settle → `GET /api/ansich/tasks/{task_id}/environment` 返回 scope 卡(environment_scope/coverage/provider/metrics 齐全);无环境数据的 Task 返回 `{"task_id":..., "scopes": []}`。
2. unknown 完整下发:uninstrumented scope 的 belief `value == {"value": "unknown", ...}` 且 `evidence_obs_ids == []`(不丢 unknown——concepts 第 9 条第 6 款)。
3. alert filter:`GET /api/ansich/operations/alerts?type=environment_pressure` 200 且只返回该类型;非法类型仍 422。
4. ToolCall 详情:有 per_command 样本的 bash 调用,detail 响应含 additive `environment_sample` 字段;无样本为 `null`(老字段不变)。
5. 权限:非 admin 401/403(照该文件现有权限测试)。

- [ ] **Step 2: backend 读方法**(sql.py)

`get_task_environment(task_id)`:
1. 查 `AnsichRelationRow`(subject=task, predicate=within_scope, role in ("sandbox_boundary","host_environment")) → scope ids + `AnsichScopeRow` 详情;
2. 对每个 scope:coverage 行 + state 行 → metric views;`AnsichCurrentBeliefRow` where `subject_id==scope_id and field_name like 'environment_%'` join assertion + evidence → belief views;`AnsichAlertRow` where subject 且 type in 环境类型(按 opened_at 降序,限 20)→ alert summaries;
3. 有 state/coverage 行但当前 belief 缺失的维度,合成 `unassessed`-风格 unknown belief(`source=NamedVersion(name="none", version="1")`,对齐 quality belief 的惯例)。

`AnsichService.get_task_environment` 直通 backend;`deerflow/ansich/__init__.py` 的降级 stub 返回 `TaskEnvironmentView(task_id=task_id, scopes=())`(照 `get_task_usage_breakdown` stub 的写法)。

- [ ] **Step 3: 路由**

`ansich.py`:
- alert filter Literal(511 行附近)追加 `"environment_pressure"`, `"environment_leak_suspected"`;
- 新路由(放在 `get_task_budgets` 之后):

```python
@router.get("/tasks/{task_id}/environment")
async def get_task_environment(task_id: str, request: Request) -> dict:
    service = _require_ansich_service(request)  # 用该文件现有的服务获取/503 守卫 helper,名字以实际为准
    view = await service.get_task_environment(task_id)
    return view.model_dump(mode="json")
```

- ToolCall 详情:找到现有 ToolCall detail 序列化处(`grep -n "tool_call" backend/app/gateway/routers/ansich.py | head`),在响应 dict 加 `"environment_sample": ...`,由 backend 读 `AnsichToolEnvSampleRow`(service 加一个 `get_tool_environment_sample(tool_call_id)`,查无返回 None;或并入现有 tool detail 读方法——按现有读方法结构就近选择,保持一次查询)。

- [ ] **Step 4: 跑测试通过;Step 5: Commit**

```bash
git add backend/packages/ansich/ansich/environment.py backend/packages/ansich/ansich/service.py backend/packages/harness/deerflow/ansich/persistence/sql.py backend/packages/harness/deerflow/ansich/__init__.py backend/app/gateway/routers/ansich.py backend/tests/test_gateway_ansich_environment.py
git commit -m "feat(ansich): task environment read API, environment alert filter, tool env sample"
```

---

### Task 11: 前端 — 运行环境面板与 Alert 类型接入

**Files:**
- Modify: `frontend/src/core/ansich/types.ts`(新类型)
- Modify: `frontend/src/core/ansich/api.ts`(fetch)
- Modify: `frontend/src/core/ansich/presentation.ts`(标记 → 徽标文案映射)
- Create: `frontend/src/components/workspace/ansich/environment-panel.tsx`
- Modify: `frontend/src/components/workspace/ansich/index.ts`(导出)
- Modify: `frontend/src/components/workspace/ansich/alert-panel.tsx`(两个新类型的标签/severity 展示)
- Modify: Task 详情页组合处(先 `grep -rn "task-hero\|TaskHero\|budget-panel" frontend/src/app/workspace/ansich | head` 定位挂载点,把 `EnvironmentPanel` 挂在 budget 面板之后)
- Test: `frontend/tests/unit/core/ansich/environment-presentation.test.ts`

**Interfaces:**
- Consumes: Task 10 的 JSON 形状(字段名逐字对应 view 模型)。
- Produces: `TaskEnvironmentView`/`EnvironmentScopeView` TS 类型;`fetchTaskEnvironment(taskId): Promise<TaskEnvironmentView>`;`environmentScopeBadge(scope)` / `coverageBadge(coverage)` 展示映射。

- [ ] **Step 1: 写失败测试**(presentation 纯函数)

```typescript
import { describe, expect, it } from "vitest";
import { coverageBadge, environmentScopeBadge } from "~/core/ansich/presentation";

describe("environment presentation", () => {
  it("labels the three environment scopes distinctly and honestly", () => {
    expect(environmentScopeBadge("container").label).toBe("容器实测");
    expect(environmentScopeBadge("process_group").label).toBe("进程组快照");
    expect(environmentScopeBadge("host_shared").label).toBe("宿主共享");
  });
  it("renders uninstrumented as explicit 未观测, never ok/green", () => {
    const badge = coverageBadge("uninstrumented");
    expect(badge.label).toBe("未观测");
    expect(badge.tone).not.toBe("positive");
  });
  it("renders unknown belief as 未知 tone, not empty", () => {
    const badge = coverageBadge("continuous");
    expect(badge.label).toBe("连续采样");
  });
});
```

(vitest 的既有配置/导入风格以 `frontend/tests/unit/core/ansich` 现有测试为准。)

- [ ] **Step 2: 类型与 api**

`types.ts` 加与 Task 10 view 逐字段对应的接口(`environment_scope`、`coverage`、`metrics[]`、`beliefs[]`、`alerts[]`,unknown/nullable 字段全部显式 `| null`);`api.ts` 加 `fetchTaskEnvironment(taskId)`(照现有 fetch helper 的 base path/错误处理)。

- [ ] **Step 3: 组件**

`environment-panel.tsx`:每个 scope 一张卡——标题 `display_label`,右上 `environmentScopeBadge` + `coverageBadge`(用现有 `signal-badge.tsx`/`status-badge.tsx` 的组件惯例);指标行(fd 显示 `value/limit` 与比率,字节数用现有格式化 helper,`limit` 为 null 不显示比率);belief 状态行:`ok/warning/critical/unknown` 四态,unknown 用中性色并显式文字"未知"(禁止绿色/空白);alert 摘要行链接到现有 alert 详情。`process_group` 卡片固定附一行说明文案:"单命令消耗快照,非沙箱存量"。空 scopes → 面板显示"该 Task 无环境观测记录"。

`alert-panel.tsx`:类型标签映射加 `environment_pressure → "环境压力"`、`environment_leak_suspected → "疑似 fd 泄漏"`;detail 的 possibly-affected 列表标题文案用**"采样时正在运行的 Task"**(不用"受影响")。

- [ ] **Step 4: `pnpm check && pnpm test` 通过;Step 5: Commit**

```bash
git add frontend/src/core/ansich frontend/src/components/workspace/ansich frontend/src/app/workspace/ansich frontend/tests/unit/core/ansich
git commit -m "feat(ansich-ui): task environment panel with explicit scope/coverage marks"
```

---

### Task 12: 文档同步(concepts 第 9 条,同一 change set 收尾)

**Files:**
- Modify: `ansich/docs/concepts.md`(§7 Scope 段落加 `host` kind;新增"§X 环境观测"小节:三层标记语义、per_command 零告警、泄漏规则输入限制、possibly-affected 措辞)
- Modify: `ansich/docs/ansich-design-document.md`(世界模型加环境证据来源;按该文档现有结构就近插入)
- Create: `ansich/docs/plans/environment-observability.md`(指向 spec 与本计划,记录测试矩阵;格式照 `ansich/docs/plans/` 现有 Phase 文档)
- Modify: `ansich/docs/plans/README.md`(登记)
- Modify: `backend/AGENTS.md`(Ansich 段落追加一段:environment probe/projector/assessor/alert 类型、配置键、`0026` 迁移、per_command 开关与 telemetry 模块)
- Modify: `CHANGELOG.md`(未发布节加一行)

- [ ] **Step 1: 逐文件更新**(内容以 spec 各节为准逐条摘录,不新造术语;concepts.md 的新小节必须包含三条硬规则原文级表述:environment_scope 语义分级、缺数据永远 unknown、per_command 不喂泄漏规则)
- [ ] **Step 2: 全量回归**

Run: `cd backend && make test && make lint && cd ../frontend && pnpm check && pnpm test`
Expected: 全绿

- [ ] **Step 3: Commit**

```bash
git add ansich/docs backend/AGENTS.md CHANGELOG.md
git commit -m "docs(ansich): environment observability concepts, design-doc, and plan registry sync"
```

---

## Self-Review 记录

- **Spec 覆盖**:§3 契约 → Task 1/2;§4 采集(probe/per-command/声明/配置/不做项)→ Task 3-6;§5 投影/assessor/Alert/per_command 克制/失效路径 → Task 7-9;§6 API/前端 → Task 10-11;§7 测试矩阵 → 各任务 Step 1 逐条落位(blocking-io 锚点在 Task 5,harness 边界在 Task 3,replay 在 Task 8,跃迁去重与规则拒收在 Task 9);§8 文档同步 → Task 12。
- **类型一致性**:`EnvironmentSamplePayload`/`EnvironmentReading`/行模型列名/`field_name` 前缀/HTTP JSON 字段在 Task 1→4→7→8→9→10→11 间逐字保持;泄漏阈值三处(spec、Task 2 config、Task 9 规则)一致(6/60/50)。
- **已知实现级留白(有意)**:四处标注了"inspection step"(LocalSandboxProvider 构造签名、AIO 内存映射属性名、tool_middleware 上下文取值、Task 详情页挂载点)——这些是仓库私有命名,执行时以 grep 结果为准,验收标准已写明;其余无 TBD。

import asyncio
import threading
import time

import pytest
from ansich.safety import scope_entity_id, scope_reference_hash

from deerflow.ansich.probes.env_samplers import EnvironmentReading
from deerflow.ansich.probes.environment import (
    AnsichEnvironmentProbe,
    ProbeResolution,
    ScopeDecl,
    _resolve_aio,
    _resolve_local,
)


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
    calls = {"n": 0}

    def resolve():
        calls["n"] += 1
        return None

    service = FakeService()
    probe = AnsichEnvironmentProbe(
        service,
        task_id="6f000000-0000-4000-8000-000000000001",
        run_id="run-1",
        interval_seconds=0.05,
        is_owner=lambda: True,
        resolve=resolve,
    )
    probe.start()
    await asyncio.sleep(0.05 * 3.5)
    await probe.stop()
    # The resolver must actually have ticked (>=1 call) so an empty `recorded`
    # proves the probe skipped ticks, not that the loop never ran at all.
    assert calls["n"] >= 1
    assert service.recorded == []


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
        service,
        task_id="6f000000-0000-4000-8000-000000000001",
        run_id="r",
        interval_seconds=0.05,
        is_owner=lambda: True,
        resolve=boom,
    )
    probe.start()
    await asyncio.sleep(0.2)
    await probe.stop()  # 不抛异常即通过


@pytest.mark.asyncio
async def test_probe_stop_is_bounded_when_resolver_hangs():
    """stop() must not inherit the resolver's worst-case duration.

    ``asyncio.to_thread``'s underlying job cannot be cancelled once running, so
    an unbounded ``await task`` in stop() would stall the worker's terminal
    sequence behind a wedged resolver (cold provider construction, AIO lock
    contention, a stuck /proc read). This pins the bound: stop() must return
    within ``stop_timeout_seconds`` even while the resolver is still blocked.
    """
    release = threading.Event()
    calls = {"n": 0}

    def hang():
        calls["n"] += 1
        release.wait()  # never set until the test releases it below
        return None

    service = FakeService()
    probe = AnsichEnvironmentProbe(
        service,
        task_id="6f000000-0000-4000-8000-000000000003",
        run_id="run-hang",
        interval_seconds=0.02,
        is_owner=lambda: True,
        resolve=hang,
        stop_timeout_seconds=0.2,
    )
    probe.start()
    await asyncio.sleep(0.05)  # let the first tick start and block in the worker thread
    assert calls["n"] >= 1

    started = time.monotonic()
    await probe.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0  # bounded well below "hangs forever"
    release.set()  # let the abandoned resolver thread exit cleanly
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_probe_skips_tick_when_reading_has_empty_metrics():
    """An empty-metrics reading must not produce a contract-invalid sample.

    ``EnvironmentSamplePayload`` rejects ``coverage="continuous"`` with empty
    metrics. A workspace dir that doesn't exist yet (local, no PSI) can
    legitimately produce ``EnvironmentReading(metrics={})`` — that tick must
    be skipped like a ``reading is None`` tick, not permanently downgraded to
    uninstrumented, so a later tick with real metrics still emits normally.
    """

    def _resolution_with_metrics(metrics):
        decl = ScopeDecl("host", "host-1", "host_environment")
        return ProbeResolution(
            scopes=(decl,),
            coverage="continuous",
            provider="local",
            reading_scope=decl,
            reading=EnvironmentReading("host_shared", metrics),
        )

    calls = {"n": 0}

    def resolve():
        calls["n"] += 1
        if calls["n"] == 1:
            return _resolution_with_metrics({})
        return _resolution_with_metrics({"disk_free_bytes": {"value": 1, "limit": 2}})

    service = FakeService()
    probe = AnsichEnvironmentProbe(
        service,
        task_id="6f000000-0000-4000-8000-000000000004",
        run_id="run-empty-metrics",
        interval_seconds=0.05,
        is_owner=lambda: True,
        resolve=resolve,
    )
    probe.start()
    await asyncio.sleep(0.05 * 3.5)
    await probe.stop()

    assert calls["n"] >= 2
    samples = [o for o in service.recorded if o.kind == "environment.sampled"]
    assert len(samples) >= 1
    for sample in samples:
        assert sample.payload["metrics"] == {"disk_free_bytes": {"value": 1, "limit": 2}}


@pytest.mark.asyncio
async def test_probe_ticks_immediately_without_waiting_a_full_interval():
    """The first tick must not be gated behind a full interval.

    The local sandbox Scope has to exist before an early ``bash`` emits its
    ``tool:{id}:env`` per-command sample; otherwise that observation waits on a
    Scope a short run never declares, and the dependency wait eventually
    becomes a failed job plus degraded Ansich health.
    """

    service = FakeService()
    probe = AnsichEnvironmentProbe(
        service,
        task_id="6f000000-0000-4000-8000-000000000005",
        run_id="run-first-tick",
        interval_seconds=10.0,  # far longer than the sleep below
        is_owner=lambda: True,
        resolve=lambda: _container_resolution(),
    )
    probe.start()
    await asyncio.sleep(0.1)
    await probe.stop()

    scope_obs = [o for o in service.recorded if o.kind == "scope.snapshotted"]
    samples = [o for o in service.recorded if o.kind == "environment.sampled"]
    assert len(scope_obs) == 1
    assert len(samples) == 1


@pytest.mark.asyncio
async def test_probe_does_not_tick_when_ownership_is_lost_before_the_first_tick():
    """The immediate first tick still runs the ownership check first."""

    service = FakeService()
    probe = AnsichEnvironmentProbe(
        service,
        task_id="6f000000-0000-4000-8000-000000000006",
        run_id="run-first-tick-not-owner",
        interval_seconds=10.0,
        is_owner=lambda: False,
        resolve=lambda: _container_resolution(),
    )
    probe.start()
    await asyncio.sleep(0.1)
    await probe.stop()

    assert service.recorded == []


class _FakeSandbox:
    def __init__(self, sandbox_id):
        self.id = sandbox_id


class _FakeAioProvider:
    def __init__(self, sandbox):
        self._sandbox = sandbox

    def peek_thread_sandbox(self, user_id, thread_id):
        return self._sandbox


def _projected_sandbox_scope_id(sandbox_ref: str) -> str:
    """Mirror how the task-structural projector derives a sandbox Scope id.

    ``_project_scopes`` (and ``ansich.memory``'s in-memory twin) resolve a
    Task's ``within_scope`` sandbox Scope from ``task.created``'s
    ``sandbox_ref`` as ``scope_entity_id("sandbox", scope_reference_hash(
    "sandbox", sandbox_ref))``, with no extra normalization of its own.
    """

    return scope_entity_id("sandbox", scope_reference_hash("sandbox", sandbox_ref))


def test_aio_resolver_declares_the_provider_sandbox_id_as_its_scope(monkeypatch):
    """The AIO probe Scope must be the same entity Tasks attach to.

    ``task.created``'s ``sandbox_ref`` is the provider sandbox id (AIO:
    ``sha256(f"{user_id}:{thread_id}")[:8]``). Declaring a different ref here
    would mint a second Scope entity for one container, so AIO child Tasks
    could not join back and an environment Alert's
    ``possibly_affected_task_ids`` would omit the subagents sharing it.
    """

    sandbox_id = "a1b2c3d4"
    monkeypatch.setattr(
        "deerflow.ansich.probes.environment.get_sandbox_provider",
        lambda: _FakeAioProvider(_FakeSandbox(sandbox_id)),
    )
    # No container id is reachable on the fake, so this lands on the
    # uninstrumented declaration branch — which declares the same ScopeDecl the
    # instrumented branch does.
    resolution = _resolve_aio(user_id="user-1", thread_id="thread-1")

    (decl,) = resolution.scopes
    assert decl.scope_kind == "sandbox"
    assert decl.external_ref == sandbox_id
    declared_scope_id = scope_entity_id(decl.scope_kind, scope_reference_hash(decl.scope_kind, decl.external_ref))
    assert declared_scope_id == _projected_sandbox_scope_id(sandbox_id)


def test_local_resolver_sandbox_scope_matches_the_local_sandbox_id(monkeypatch):
    """``LocalSandboxProvider`` ids per-thread sandboxes exactly ``local:{thread_id}``."""

    resolution = _resolve_local(user_id="user-1", thread_id="thread-1")
    sandbox_decls = [decl for decl in resolution.scopes if decl.scope_kind == "sandbox"]
    assert [decl.external_ref for decl in sandbox_decls] == ["local:thread-1"]

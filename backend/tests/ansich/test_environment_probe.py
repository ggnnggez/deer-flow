import asyncio

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

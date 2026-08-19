"""Regression anchor: ``AnsichEnvironmentProbe``'s resolver call must not block the loop.

``_record_tick`` offloads the injected ``resolve`` callable via
``asyncio.to_thread`` because provider dispatch (``build_environment_resolver``)
does real filesystem reads — ``/proc`` stat, disk usage, cgroup files. This
anchor drives a real blocking file read from a fake resolver and runs one
probe tick under the strict Blockbuster gate (see ``tests/blocking_io/conftest.py``),
asserting no ``BlockingError`` is raised — i.e. the resolver never runs
directly on the event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deerflow.ansich.probes.environment import AnsichEnvironmentProbe

pytestmark = pytest.mark.asyncio


class _FakeService:
    def __init__(self):
        self.recorded = []

    def record(self, envelope):
        self.recorded.append(envelope)


async def test_probe_tick_offloads_resolver_blocking_io(tmp_path: Path) -> None:
    proc_self_stat = Path("/proc/self/stat")
    if proc_self_stat.exists():
        read_target = proc_self_stat
    else:
        read_target = tmp_path / "fake-stat"
        read_target.write_text("13195 (fake) S 1 0 0", encoding="utf-8")

    def resolve():
        # Real synchronous filesystem IO — must run off the event loop.
        read_target.read_text()
        return None

    service = _FakeService()
    probe = AnsichEnvironmentProbe(
        service,
        task_id="6f000000-0000-4000-8000-000000000002",
        run_id="run-blocking-io",
        interval_seconds=0.05,
        is_owner=lambda: True,
        resolve=resolve,
    )
    probe.start()
    await asyncio.sleep(0.12)
    await probe.stop()

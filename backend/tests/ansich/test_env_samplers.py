import uuid
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


def test_local_provider_peek():
    # NOTE (deviation from brief's literal example): the real
    # ``LocalSandboxProvider.__init__`` takes only ``max_cached_threads`` (no
    # ``base_dir`` kwarg) — see local_sandbox_provider.py. A unique thread_id
    # is enough isolation for this assertion without needing to redirect
    # ``get_paths().base_dir`` to tmp_path (other simple provider tests in
    # this suite, e.g. test_local_sandbox_telemetry.py, also construct
    # ``LocalSandboxProvider()`` with no isolation fixture).
    from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider

    provider = LocalSandboxProvider()
    thread_id = f"ansich-peek-{uuid.uuid4()}"
    assert provider.peek_thread_sandbox(None, thread_id) is not None


def test_base_provider_peek_defaults_to_none():
    from deerflow.sandbox.sandbox_provider import SandboxProvider

    # NOTE (deviation from brief's literal example): the real abstract
    # surface has three abstractmethods (acquire/get/release); reset() is a
    # concrete no-op hook, not abstract, so Dummy does not need to override
    # it. Confirmed via
    # `grep -n "def \|abstractmethod" sandbox_provider.py`.
    class Dummy(SandboxProvider):
        def acquire(self, thread_id=None, *, user_id=None):  # pragma: no cover
            raise NotImplementedError

        def get(self, sandbox_id):  # pragma: no cover
            return None

        def release(self, sandbox_id):  # pragma: no cover
            pass

    assert Dummy().peek_thread_sandbox(None, "t") is None


def test_environment_reading_is_frozen_dataclass():
    reading = EnvironmentReading(environment_scope="host_shared", metrics={})
    assert reading.environment_scope == "host_shared"
    assert reading.metrics == {}

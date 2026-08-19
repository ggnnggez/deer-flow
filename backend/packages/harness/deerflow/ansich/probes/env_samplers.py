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

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


_LAST_SAMPLE: ContextVar[CommandResourceSample | None] = ContextVar("deerflow_last_command_resource_sample", default=None)


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

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from deerflow.sandbox import telemetry
from deerflow.sandbox.telemetry import ProcessGroupSampler

pytestmark = pytest.mark.skipif(not Path("/proc").exists(), reason="requires /proc")


def test_sampler_collects_io_and_fd_from_real_process_group(tmp_path):
    # NOTE (deviation from brief's literal example): /dev/null is a character
    # device, so writes to it never register in /proc/<pid>/io's write_bytes
    # (only wchar, which this sampler intentionally does not read). Writing to
    # a real file under tmp_path with an explicit fsync is what actually
    # exercises the write_bytes accounting this test means to assert on.
    target = tmp_path / "sink.bin"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import os, time; f=open({str(target)!r},'wb'); f.write(b'x'*65536); f.flush(); os.fsync(f.fileno()); time.sleep(3)",
        ],
        start_new_session=True,
    )
    try:
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
        provider = LocalSandboxProvider()
        sandbox_id = provider.acquire()
        sandbox = provider.get(sandbox_id)
        sandbox.execute_command("head -c 4096 /dev/zero > /dev/null")
        sample = telemetry.consume_command_sample()
        assert sample is not None
    finally:
        telemetry.set_per_command_sampling_enabled(False)

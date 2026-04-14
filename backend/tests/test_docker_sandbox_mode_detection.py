"""Regression tests for docker sandbox mode detection logic."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "docker.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)

if BASH_EXECUTABLE is None:
    pytestmark = pytest.mark.skip(reason="bash is required for docker.sh detection tests")


def _detect_mode_with_config(config_content: str) -> str:
    """Write config content into a temp project root and execute detect_sandbox_mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        (tmp_root / "config.yaml").write_text(config_content, encoding="utf-8")

        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmp_root}' && detect_sandbox_mode"

        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

        return output


def test_detect_mode_defaults_to_local_when_config_missing():
    """No config file should default to local mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmpdir}' && detect_sandbox_mode"
        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

    assert output == "local"


def test_detect_mode_local_provider():
    """Local sandbox provider should map to local mode."""
    config = """
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"


def test_detect_mode_aio_without_provisioner_url():
    """AIO sandbox without provisioner_url should map to aio mode."""
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_provisioner_with_url():
    """AIO sandbox with provisioner_url should map to provisioner mode."""
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "provisioner"


def test_detect_mode_ignores_commented_provisioner_url():
    """Commented provisioner_url should not activate provisioner mode."""
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  # provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_unknown_provider_falls_back_to_local():
    """Unknown sandbox provider should default to local mode."""
    config = """
sandbox:
  use: custom.module:UnknownProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"


def test_default_deer_flow_root_uses_windows_path_for_wsl_docker_desktop():
    """WSL + Docker Desktop needs slash paths that the Windows Docker daemon can bind-mount."""
    command = rf"""
source '{SCRIPT_PATH}'
PROJECT_ROOT='/mnt/e/code/deer-flow'
export WSL_DISTRO_NAME='Ubuntu'
docker() {{
  if [ "$1" = "info" ]; then
    echo 'Docker Desktop'
  fi
}}
wslpath() {{
  echo 'E:/code/deer-flow'
}}
default_deer_flow_root
"""
    output = subprocess.check_output(
        [BASH_EXECUTABLE, "-lc", command],
        text=True,
        encoding="utf-8",
    ).strip()

    assert output == "E:/code/deer-flow"


def test_default_deer_flow_root_keeps_wsl_path_for_linux_docker_engine():
    """A Docker Engine running inside WSL can resolve the native /mnt path."""
    command = rf"""
source '{SCRIPT_PATH}'
PROJECT_ROOT='/mnt/e/code/deer-flow'
export WSL_DISTRO_NAME='Ubuntu'
docker() {{
  if [ "$1" = "info" ]; then
    echo 'Docker Engine - Community'
  fi
}}
wslpath() {{
  echo 'E:/code/deer-flow'
}}
default_deer_flow_root
"""
    output = subprocess.check_output(
        [BASH_EXECUTABLE, "-lc", command],
        text=True,
        encoding="utf-8",
    ).strip()

    assert output == "/mnt/e/code/deer-flow"


def test_default_deer_flow_root_returns_project_root_on_non_wsl():
    """Native Linux / macOS hosts must keep PROJECT_ROOT unchanged."""
    # Override is_wsl to force the non-WSL branch regardless of where the
    # test actually runs (CI on real WSL machines would otherwise have a
    # /proc/version matching 'microsoft' and escape this code path).
    command = rf"""
source '{SCRIPT_PATH}'
PROJECT_ROOT='/home/alice/code/deer-flow'
unset WSL_DISTRO_NAME
is_wsl() {{ return 1; }}
docker() {{
  if [ "$1" = "info" ]; then
    echo 'Docker Desktop'
  fi
}}
wslpath() {{
  echo 'SHOULD_NOT_BE_USED'
}}
default_deer_flow_root
"""
    output = subprocess.check_output(
        [BASH_EXECUTABLE, "-lc", command],
        text=True,
        encoding="utf-8",
    ).strip()

    assert output == "/home/alice/code/deer-flow"

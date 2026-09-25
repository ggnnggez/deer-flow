"""Verify the built distribution, outside the example's source import path."""

import argparse
import asyncio
import importlib.metadata
import inspect
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-dir", required=True, type=Path)
    args = parser.parse_args()
    installed = args.installed_dir.resolve(strict=True)
    sys.path.insert(0, str(installed))

    from deerflow_extension_api import AgentBuildContext, AgentScope
    from deerflow_extension_api.auth import ExtensionPrincipal
    from deerflow_extension_api.plugins import ActionContext

    from deerflow.extensions.loader import ExtensionSpec, load_extensions

    distribution = importlib.metadata.distribution("deerflow-extension-context-residency")
    assert Path(distribution.locate_file("")).resolve() == installed
    entries = [entry for entry in distribution.entry_points if entry.group == "deerflow.extensions"]
    assert [(entry.name, entry.value) for entry in entries] == [("context-residency", "deerflow_extension_context_residency:install")]
    installer = entries[0].load()
    assert callable(installer)
    assert Path(inspect.getfile(installer)).resolve().is_relative_to(installed)
    assert distribution.metadata["License-Expression"] == "MIT"
    assert distribution.metadata.get_all("License-File") == ["LICENSE"]

    for enabled in (False, True):
        loaded, diagnostics = load_extensions([ExtensionSpec(use=entries[0].value, config={"enabled": enabled})])
        assert not diagnostics, diagnostics
        ((_, plugin),) = loaded.plugins
        assert plugin.namespace == "community.context-residency" and plugin.enabled == enabled
        ((_, contributor),) = loaded.middleware_contributors
        for scope in (AgentScope.LEAD, AgentScope.SUBAGENT):
            placements = contributor.contribute_middlewares(None, AgentBuildContext(scope=scope))
            assert [p.placement.value for p in placements] == (["model_logical", "model_physical"] if enabled else [])
        assert len(loaded.task_lifecycle) == 1
        assert len(loaded.context_compaction_observers) == 1
        assert len(loaded.services) == 1
        assert len(loaded.routers) == 1
        (action,) = plugin.backend
        status = asyncio.run(action.handler({}, ActionContext(ExtensionPrincipal("package-test"), {})))
        assert {"enabled", "running", "queue_depth", "accepted", "dropped", "flushed", "write_failures", "estimator", "max_attempts"} <= set(status)
        assert status["enabled"] == enabled and status["running"] is False
    print("Installed wheel entry point, license, host registration and enable/disable verified.")


if __name__ == "__main__":
    main()

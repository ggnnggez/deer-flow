"""Context residency for DeerFlow, as an out-of-tree extension.

Records, per task, which content blocks every model request carried — the
ordered member inventory of each physical provider call, the logical decision
it belongs to, and each context compaction with the blocks it removed and the
summary it produced — so a reader can answer when a block entered the context,
how long it stayed, and what removed it. Metadata only: hashes, kinds, sizes and
positions; no message bodies.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import BackendAction, BrowserAssets, PluginContribution, SettingsField, extension

from .lifecycle import ResidencyCompactionObserver, ResidencyLifecycle
from .options import Options
from .probes import ResidencyContributor
from .recorder import RecorderHandle
from .router import build_router
from .service import ResidencyService

logger = logging.getLogger(__name__)

NAMESPACE = "community.context-residency"


@extension(api="0.2.6", name="context-residency")
def install(registry: Any, config: Mapping[str, Any]) -> None:
    options = Options.model_validate(dict(config))
    handle = RecorderHandle(options.queue_capacity)
    service = ResidencyService(handle, options)

    registry.task_lifecycle(ResidencyLifecycle(handle, options))
    registry.context_compaction_observer(ResidencyCompactionObserver(handle, options))
    registry.middlewares(ResidencyContributor(handle, options))
    registry.service(service)
    registry.routers((build_router(service),))

    async def status(payload: Any, context: Any) -> dict[str, Any]:
        if payload:
            raise ValueError("status takes no arguments")
        return service.status()

    accepted = registry.plugin(
        PluginContribution(
            namespace=NAMESPACE,
            title="上下文留存 / Context residency",
            description="记录每次模型请求携带了哪些内容块：何时进入、留了多久、被什么移出。仅元数据，管理员可读。",
            enabled=options.enabled,
            # The page: one self-contained module plus its stylesheet, built
            # from ``frontend/`` into ``static/dist`` and listed in
            # ``ui_manifest.json`` (``assets-v1``).
            frontend=BrowserAssets("context-residency.v1", Path(__file__).parent),
            fields=(SettingsField("max_attempts", "每个任务读取的 attempt 上限 / Attempts returned per task read", "integer", options.max_attempts, minimum=1, maximum=5000),),
            backend=(BackendAction("status", status),),
        )
    )
    if accepted is not True:
        logger.info("context-residency: this host has no plugin UI support; capture and the admin API are installed without the page or a catalog entry")

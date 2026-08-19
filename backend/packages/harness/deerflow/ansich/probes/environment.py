"""Outer environment sampling probe.

Mirrors ``task_heartbeat.py``'s loop/ownership/fail-open skeleton. Where the
heartbeat proves outer Run liveness, this probe records best-effort OS-level
environment readings (disk/PSI pressure on local, fd/io/rss on AIO
containers) as ``environment.sampled`` Observations, declaring the sampled
Scope once via ``scope.snapshotted`` before the first sample.

Collection is deliberately fail-open: a resolver failure, a missing sandbox,
or a Run losing ownership never affects the DeerFlow Run itself — the worst
outcome is a gap in environment evidence.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from threading import Lock
from uuid import uuid4

from ansich import AnsichService, ObservationEnvelope
from ansich.safety import scope_entity_id, scope_reference_hash

from deerflow.ansich.probes.env_samplers import (
    EnvironmentReading,
    resolve_container_cgroup_dir,
    sample_aio_container,
    sample_local_host,
)
from deerflow.config.paths import get_paths
from deerflow.sandbox.sandbox_provider import get_sandbox_provider

logger = logging.getLogger(__name__)

_PRODUCER_INSTANCE_ID = str(uuid4())
_PRODUCER_SEQUENCE = count(1)
_PRODUCER_SEQUENCE_LOCK = Lock()


def _next_producer_sequence() -> int:
    with _PRODUCER_SEQUENCE_LOCK:
        return next(_PRODUCER_SEQUENCE)


@dataclass(frozen=True)
class ScopeDecl:
    """A Scope the resolver wants declared before (or instead of) sampling it."""

    scope_kind: str
    external_ref: str
    relation_role: str


@dataclass(frozen=True)
class ProbeResolution:
    """One tick's provider-dispatched resolution: what to declare and what was read.

    ``coverage`` is honest, never guessed: ``"continuous"`` when ``reading`` is
    (or will be) genuinely sampled on every tick, ``"uninstrumented"`` when the
    provider cannot be sampled at all (declare the Scope once, then stop).
    ``reading is None`` with ``coverage == "continuous"`` means "sandbox not
    ready yet this tick" — an explicit skip, never a synthesized zero reading.
    """

    scopes: tuple[ScopeDecl, ...]
    coverage: str
    provider: str
    reading_scope: ScopeDecl | None
    reading: EnvironmentReading | None


class AnsichEnvironmentProbe:
    """Emit environment evidence outside the Agent graph stream.

    Declares every Scope the resolver names once, then — for continuously
    instrumented providers — records a sample on each tick. For providers
    that cannot be instrumented, it declares a single uninstrumented sample
    and stops itself; there is nothing further to tick toward.
    """

    def __init__(
        self,
        service: AnsichService,
        *,
        task_id: str,
        run_id: str,
        interval_seconds: float,
        is_owner: Callable[[], bool],
        resolve: Callable[[], ProbeResolution | None],
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._service = service
        self._task_id = task_id
        self._run_id = run_id
        self._interval_seconds = interval_seconds
        self._is_owner = is_owner
        self._resolve = resolve
        self._started_at = datetime.now(UTC)
        self._last_tick_at: datetime | None = None
        self._tick = 0
        self._declared_scopes: set[tuple[str, str]] = set()
        self._declaration_sent = False
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run(),
            name=f"ansich-environment-probe:{self._run_id}",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                "Ansich environment probe shutdown failed for run %s",
                self._run_id,
                exc_info=True,
            )
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
                return
            except TimeoutError:
                pass

            if not self._is_owner():
                logger.info(
                    "Run %s no longer belongs to this worker; stopping Ansich environment probe",
                    self._run_id,
                )
                return
            await self._record_tick()

    async def _record_tick(self) -> None:
        try:
            resolution = await asyncio.to_thread(self._resolve)
        except Exception:
            logger.warning("Ansich environment sampling failed for run %s", self._run_id, exc_info=True)
            return
        if resolution is None:
            return
        try:
            now = datetime.now(UTC)
            for decl in resolution.scopes:
                key = (decl.scope_kind, decl.external_ref)
                if key in self._declared_scopes:
                    continue
                self._service.record(
                    ObservationEnvelope.scope_snapshotted(
                        task_id=self._task_id,
                        run_id=self._run_id,
                        occurred_at=now,
                        scope_kind=decl.scope_kind,
                        external_ref=decl.external_ref,
                        relation_role=decl.relation_role,
                        source_event_id=f"run:{self._run_id}:env-scope:{decl.scope_kind}:{decl.external_ref}",
                        producer_seq=_next_producer_sequence(),
                        producer_name="deerflow-environment-probe",
                        producer_version="1",
                        producer_instance_id=_PRODUCER_INSTANCE_ID,
                    )
                )
                self._declared_scopes.add(key)
            if resolution.coverage == "uninstrumented":
                if not self._declaration_sent:
                    self._emit_sample(resolution, now, sample_count=0, metrics={})
                    self._declaration_sent = True
                self._stop_event.set()  # 声明一次后循环无事可做
                return
            if resolution.reading is None:
                return  # 沙箱尚未就绪:显式覆盖空洞,不猜
            self._tick += 1
            self._emit_sample(resolution, now, sample_count=1, metrics=resolution.reading.metrics)
            self._last_tick_at = now
        except Exception:
            logger.warning("Ansich environment observation failed for run %s", self._run_id, exc_info=True)

    def _emit_sample(
        self,
        resolution: ProbeResolution,
        now: datetime,
        *,
        sample_count: int,
        metrics: dict[str, dict[str, int | None]],
    ) -> None:
        scope = resolution.reading_scope
        if scope is None:
            return
        ref_hash = scope_reference_hash(scope.scope_kind, scope.external_ref)  # type: ignore[arg-type]
        scope_id = scope_entity_id(scope.scope_kind, ref_hash)  # type: ignore[arg-type]
        if resolution.coverage == "uninstrumented":
            source_event_id = f"run:{self._run_id}:env:{scope_id}:decl"
        else:
            source_event_id = f"run:{self._run_id}:env:{scope_id}:{self._tick}"
        window_started_at = self._last_tick_at or self._started_at
        if resolution.reading is not None:
            # The reading's own EnvironmentScopeKind ("container" / "host_shared").
            environment_scope = resolution.reading.environment_scope
        else:
            # Uninstrumented declarations in this module are always sandbox-kind
            # Scopes (AIO cgroup unavailable, or another containerized provider),
            # so "container" is the closest EnvironmentScopeKind describing what
            # would have been sampled had the provider been instrumented.
            environment_scope = "container"
        payload: dict[str, object] = {
            "coverage": resolution.coverage,
            "provider": resolution.provider,
            "environment_scope": environment_scope,
            "metrics": metrics,
            "window": {
                "started_at": window_started_at.isoformat(),
                "ended_at": now.isoformat(),
                "sample_count": sample_count,
            },
        }
        self._service.record(
            ObservationEnvelope.environment_sampled(
                task_id=self._task_id,
                run_id=self._run_id,
                occurred_at=now,
                scope_id=scope_id,
                payload=payload,
                source_event_id=source_event_id,
                producer_seq=_next_producer_sequence(),
                producer_name="deerflow-environment-probe",
                producer_version="1",
                producer_instance_id=_PRODUCER_INSTANCE_ID,
            )
        )


def _provider_class_name(use_path: str) -> str:
    """Return the bare class name from a ``module.path:ClassName`` config string."""

    return use_path.rsplit(":", 1)[-1] if use_path else "unknown"


def _resolve_local(*, user_id: str, thread_id: str) -> ProbeResolution:
    host_decl = ScopeDecl("host", socket.gethostname(), "host_environment")
    sandbox_decl = ScopeDecl("sandbox", f"local:{thread_id}", "sandbox_boundary")
    workspace_path = get_paths().sandbox_work_dir(thread_id, user_id=user_id)
    reading = sample_local_host(workspace_path)
    return ProbeResolution(
        scopes=(host_decl, sandbox_decl),
        coverage="continuous",
        provider="local",
        reading_scope=host_decl,
        reading=reading,
    )


def _aio_container_id(provider: object, sandbox: object) -> str | None:
    """Best-effort container id lookup for an AIO sandbox.

    ``SandboxProvider.peek_thread_sandbox`` (Task 4) returns only the bare
    ``Sandbox`` instance; ``AioSandboxProvider`` keeps the matching
    ``SandboxInfo`` (which carries ``container_id``) in its own private
    ``_sandbox_infos`` map keyed by sandbox id. Reading it here is
    best-effort and deliberately tolerant of the attribute/map shape
    changing later: any failure just falls through to "container id
    unavailable", which the resolver already treats as an uninstrumented
    declaration rather than an error.
    """

    container_id = getattr(sandbox, "container_id", None)
    if container_id:
        return str(container_id)
    sandbox_infos = getattr(provider, "_sandbox_infos", None)
    if not sandbox_infos:
        return None
    info = sandbox_infos.get(getattr(sandbox, "id", None))
    info_container_id = getattr(info, "container_id", None) if info is not None else None
    return str(info_container_id) if info_container_id else None


def _resolve_aio(*, user_id: str, thread_id: str) -> ProbeResolution:
    provider = get_sandbox_provider()
    sandbox = provider.peek_thread_sandbox(user_id, thread_id)
    if sandbox is None:
        # Sandbox not acquired yet this tick — skip without declaring anything.
        return ProbeResolution(scopes=(), coverage="continuous", provider="aio", reading_scope=None, reading=None)
    sandbox_decl = ScopeDecl("sandbox", f"aio:{thread_id}", "sandbox_boundary")
    container_id = _aio_container_id(provider, sandbox)
    cgroup_dir = resolve_container_cgroup_dir(container_id) if container_id else None
    if cgroup_dir is None:
        return ProbeResolution(
            scopes=(sandbox_decl,),
            coverage="uninstrumented",
            provider="aio",
            reading_scope=sandbox_decl,
            reading=None,
        )
    reading = sample_aio_container(cgroup_dir)
    if reading is None:
        return ProbeResolution(
            scopes=(sandbox_decl,),
            coverage="uninstrumented",
            provider="aio",
            reading_scope=sandbox_decl,
            reading=None,
        )
    return ProbeResolution(
        scopes=(sandbox_decl,),
        coverage="continuous",
        provider="aio",
        reading_scope=sandbox_decl,
        reading=reading,
    )


def _resolve_uninstrumented_other(use_path: str, *, thread_id: str) -> ProbeResolution:
    provider_name = _provider_class_name(use_path).lower()
    decl = ScopeDecl("sandbox", f"{provider_name}:{thread_id}", "sandbox_boundary")
    return ProbeResolution(
        scopes=(decl,),
        coverage="uninstrumented",
        provider=provider_name,
        reading_scope=decl,
        reading=None,
    )


def build_environment_resolver(app_config: object, *, user_id: str, thread_id: str) -> Callable[[], ProbeResolution | None]:
    """Build the per-run resolver the worker hands to :class:`AnsichEnvironmentProbe`.

    Provider dispatch reads ``app_config.sandbox.use`` (the configured class
    path, e.g. ``deerflow.sandbox.local:LocalSandboxProvider``) once, outside
    the returned closure, mirroring the ``is_local_sandbox`` convention of
    matching provider identity by class-path substring rather than importing
    every provider module here.
    """

    sandbox_config = getattr(app_config, "sandbox", None)
    use_path = getattr(sandbox_config, "use", "") or ""

    def _resolve() -> ProbeResolution | None:
        if "LocalSandboxProvider" in use_path:
            return _resolve_local(user_id=user_id, thread_id=thread_id)
        if "AioSandboxProvider" in use_path:
            return _resolve_aio(user_id=user_id, thread_id=thread_id)
        return _resolve_uninstrumented_other(use_path, thread_id=thread_id)

    return _resolve

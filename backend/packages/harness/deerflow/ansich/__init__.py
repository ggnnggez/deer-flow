from ansich import AnsichService
from ansich.contracts import RetentionPolicy
from ansich.environment import EnvironmentThresholds
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.ansich.persistence.sql import SqlAnsichBackend


class _UnavailableBackend:
    async def persist_and_project(self, observations):
        return 0

    async def get_task(self, task_id):
        return None

    async def get_task_by_source(self, source_kind, source_id):
        return None

    async def list_tasks(
        self,
        *,
        limit=100,
        control=None,
        lifecycle_scope="all",
        from_time=None,
        to_time=None,
        cursor=None,
        root_only=False,
    ):
        return []

    async def list_observations(self, task_id):
        return []

    async def list_task_children(self, task_id):
        return []

    async def list_task_tree_spawns(self, task_id, *, direction, depth):
        return [], False

    async def get_task_usage_breakdown(self, task_id, *, scope):
        from ansich.usage import TaskUsageBreakdownView

        return TaskUsageBreakdownView(task_id=task_id, scope=scope, sources=())

    async def get_task_environment(self, task_id):
        from ansich.environment import TaskEnvironmentView

        return TaskEnvironmentView(task_id=task_id, scopes=())

    async def get_environment_history(
        self,
        scope_id,
        *,
        environment_scope,
        metric,
        window_minutes,
        max_points,
    ):
        from ansich.environment import EnvironmentHistoryView

        return EnvironmentHistoryView(
            scope_id=scope_id,
            environment_scope=environment_scope,
            metric=metric,
            window_minutes=window_minutes,
            truncated=False,
            points=(),
        )

    async def get_task_tool_env_samples(self, task_id):
        from ansich.environment import TaskToolEnvSamplesView

        return TaskToolEnvSamplesView(task_id=task_id, truncated=False, samples=())

    async def get_tool_environment_sample(self, tool_call_id):
        return None


def create_sql_ansich_service(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    queue_capacity: int = 10_000,
    queue_byte_capacity: int = 64 * 1024 * 1024,
    batch_size: int = 100,
    flush_interval_ms: int = 100,
    # Direct construction is used by the SQL integration suite, where a
    # loaded event loop can make projection settling exceed the production
    # fail-open window. Embedded runtime assembly always passes the explicit
    # AnsichConfig value (2 seconds by default), so this patient default does
    # not alter Agent execution semantics.
    terminal_flush_timeout_ms: int = 10_000,
    projector_poll_interval_ms: int = 250,
    operations_assessment_interval_ms: int = 1_000,
    writer_retry_max_attempts: int = 5,
    writer_backoff_initial_ms: int = 100,
    writer_backoff_max_ms: int = 5_000,
    writer_item_max_attempts: int = 2,
    stop_drain_timeout_ms: int = 10_000,
    shutdown_budget_ms: int = 5_000,
    health_database_timeout_ms: int = 2_000,
    projector_lease_seconds: int = 30,
    projector_max_attempts: int = 5,
    projector_dependency_timeout_seconds: int = 300,
    inline_payload_max_bytes: int = 65_536,
    heartbeat_stale_after_seconds: int = 30,
    long_dwell_seconds: int = 120,
    exact_repetition_window: int = 5,
    tool_frequency_window_seconds: int = 300,
    tool_frequency_threshold: int = 30,
    environment_sample_interval_seconds: int = 10,
    environment_thresholds: EnvironmentThresholds | None = None,
    # The host this collector files its process-wide facts under (RB1). Left
    # unset in production, where `socket.gethostname()` is the answer; injected
    # by tests that need the host-Scope identity to be a property of the test
    # rather than of the machine running it.
    hostname: str | None = None,
) -> AnsichService:
    return AnsichService(
        SqlAnsichBackend(
            session_factory,
            projector_lease_seconds=projector_lease_seconds,
            projector_max_attempts=projector_max_attempts,
            projector_dependency_timeout_seconds=projector_dependency_timeout_seconds,
            inline_payload_max_bytes=inline_payload_max_bytes,
            heartbeat_stale_after_seconds=heartbeat_stale_after_seconds,
            long_dwell_seconds=long_dwell_seconds,
            exact_repetition_window=exact_repetition_window,
            tool_frequency_window_seconds=tool_frequency_window_seconds,
            tool_frequency_threshold=tool_frequency_threshold,
            environment_sample_interval_seconds=environment_sample_interval_seconds,
            environment_thresholds=environment_thresholds,
            # One hostname, two consumers: the service mints the host Scope and
            # the backend's process-subject Alert producers write under it.
            hostname=hostname,
        ),
        queue_capacity=queue_capacity,
        queue_byte_capacity=queue_byte_capacity,
        batch_size=batch_size,
        flush_interval_ms=flush_interval_ms,
        terminal_flush_timeout_ms=terminal_flush_timeout_ms,
        projector_poll_interval_ms=projector_poll_interval_ms,
        operations_assessment_interval_ms=operations_assessment_interval_ms,
        writer_retry_max_attempts=writer_retry_max_attempts,
        writer_backoff_initial_ms=writer_backoff_initial_ms,
        writer_backoff_max_ms=writer_backoff_max_ms,
        writer_item_max_attempts=writer_item_max_attempts,
        stop_drain_timeout_ms=stop_drain_timeout_ms,
        shutdown_budget_ms=shutdown_budget_ms,
        health_database_timeout_ms=health_database_timeout_ms,
        hostname=hostname,
    )


def service_knobs_from_config(config) -> dict[str, object]:
    """Map every ``AnsichConfig`` field ``AnsichService`` itself takes (F10-27).

    Assembly has two branches — one with a session factory and one without —
    and both construct an ``AnsichService``. They used to spell this mapping out
    separately, and the no-session-factory branch quietly dropped three knobs
    (``terminal_flush_timeout_ms``, ``projector_poll_interval_ms``,
    ``operations_assessment_interval_ms``): a storage-unavailable deployment
    silently ran on library defaults for settings its operator had configured.
    That is the class of bug a duplicated argument list invites, so the mapping
    exists once and both branches splat it. Adding a service-level knob means
    adding one line *here* and nowhere else; forgetting a branch is no longer
    expressible.

    Scope is exactly the service's own constructor. Backend knobs (leases,
    attempt limits, assessor thresholds) belong to the SQL branch alone, because
    the other branch has no backend to give them to.
    """

    return {
        "queue_capacity": config.queue_capacity,
        "queue_byte_capacity": config.queue_byte_capacity,
        "batch_size": config.batch_size,
        "flush_interval_ms": config.flush_interval_ms,
        "terminal_flush_timeout_ms": config.terminal_flush_timeout_ms,
        "projector_poll_interval_ms": config.projector_poll_interval_ms,
        "operations_assessment_interval_ms": config.operations_assessment_interval_ms,
        "writer_retry_max_attempts": config.writer_retry_max_attempts,
        "writer_backoff_initial_ms": config.writer_backoff_initial_ms,
        "writer_backoff_max_ms": config.writer_backoff_max_ms,
        "writer_item_max_attempts": config.writer_item_max_attempts,
        "stop_drain_timeout_ms": config.stop_drain_timeout_ms,
        "shutdown_budget_ms": config.shutdown_budget_ms,
        "health_database_timeout_ms": config.health_database_timeout_ms,
    }


def retention_policy_from_config(config) -> RetentionPolicy:
    """Map ``AnsichRetentionConfig`` onto the framework-independent policy.

    The seam exists because ``ansich`` must not import ``deerflow`` (the
    package is framework-independent by contract), so ``run_retention`` names
    its argument in its own vocabulary and the adapter layer converts once. One
    named function rather than a splat at each call site, for the same reason
    ``service_knobs_from_config`` is one: a new retention knob then has exactly
    one place to be threaded through, and a caller that forgot one is not
    expressible.

    The containment rule is re-validated by the target model rather than trusted
    from the source. Both models enforce it, which is not redundant: a
    ``RetentionPolicy`` can be built without ever passing through configuration.
    """

    return RetentionPolicy(
        raw_payload_days=config.raw_payload_days,
        observation_days=config.observation_days,
        structural_days=config.structural_days,
        cleanup_batch_size=config.cleanup_batch_size,
    )


def environment_thresholds_from_config(assessors) -> EnvironmentThresholds:
    """Map ``AnsichAssessorConfig``'s ``environment_*`` knobs onto the rule model.

    One field per knob, prefix dropped. Kept as a named function so the mapping
    is testable without assembling a service, and so a new threshold has exactly
    one place to be threaded through.
    """

    return EnvironmentThresholds(
        fd_warn_ratio=assessors.environment_fd_warn_ratio,
        fd_critical_ratio=assessors.environment_fd_critical_ratio,
        disk_free_warn_ratio=assessors.environment_disk_free_warn_ratio,
        disk_free_critical_ratio=assessors.environment_disk_free_critical_ratio,
        psi_warn_milli=assessors.environment_psi_warn_milli,
        psi_critical_milli=assessors.environment_psi_critical_milli,
        leak_min_samples=assessors.environment_leak_min_samples,
        leak_window_seconds=assessors.environment_leak_window_seconds,
        leak_min_growth=assessors.environment_leak_min_growth,
    )


def create_embedded_ansich_service(config, session_factory):
    if not config.enabled:
        return None
    if session_factory is None:
        return AnsichService(
            _UnavailableBackend(),
            **service_knobs_from_config(config),
            unavailable_reason="storage_unavailable",
        )
    return create_sql_ansich_service(
        session_factory,
        **service_knobs_from_config(config),
        projector_lease_seconds=config.projector_lease_seconds,
        projector_max_attempts=config.projector_max_attempts,
        projector_dependency_timeout_seconds=config.projector_dependency_timeout_seconds,
        inline_payload_max_bytes=config.inline_payload_max_bytes,
        heartbeat_stale_after_seconds=config.heartbeat_stale_after_seconds,
        long_dwell_seconds=config.long_dwell_seconds,
        exact_repetition_window=config.assessors.exact_repetition_window,
        tool_frequency_window_seconds=config.assessors.tool_frequency_window_seconds,
        tool_frequency_threshold=config.assessors.tool_frequency_threshold,
        environment_sample_interval_seconds=config.effective_environment_sample_interval_seconds,
        environment_thresholds=environment_thresholds_from_config(config.assessors),
    )


__all__ = [
    "create_embedded_ansich_service",
    "create_sql_ansich_service",
    "environment_thresholds_from_config",
    "retention_policy_from_config",
    "service_knobs_from_config",
]

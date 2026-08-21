from ansich import AnsichService
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
        hostname=hostname,
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
            queue_capacity=config.queue_capacity,
            queue_byte_capacity=config.queue_byte_capacity,
            batch_size=config.batch_size,
            flush_interval_ms=config.flush_interval_ms,
            writer_retry_max_attempts=config.writer_retry_max_attempts,
            writer_backoff_initial_ms=config.writer_backoff_initial_ms,
            writer_backoff_max_ms=config.writer_backoff_max_ms,
            writer_item_max_attempts=config.writer_item_max_attempts,
            stop_drain_timeout_ms=config.stop_drain_timeout_ms,
            unavailable_reason="storage_unavailable",
        )
    return create_sql_ansich_service(
        session_factory,
        queue_capacity=config.queue_capacity,
        queue_byte_capacity=config.queue_byte_capacity,
        batch_size=config.batch_size,
        flush_interval_ms=config.flush_interval_ms,
        terminal_flush_timeout_ms=config.terminal_flush_timeout_ms,
        projector_poll_interval_ms=config.projector_poll_interval_ms,
        writer_retry_max_attempts=config.writer_retry_max_attempts,
        writer_backoff_initial_ms=config.writer_backoff_initial_ms,
        writer_backoff_max_ms=config.writer_backoff_max_ms,
        writer_item_max_attempts=config.writer_item_max_attempts,
        stop_drain_timeout_ms=config.stop_drain_timeout_ms,
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
]

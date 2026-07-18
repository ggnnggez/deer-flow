from ansich import AnsichService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.ansich.persistence.sql import SqlAnsichBackend


class _UnavailableBackend:
    async def persist_and_project(self, observations):
        return 0

    async def get_task(self, task_id):
        return None

    async def get_task_by_source(self, source_kind, source_id):
        return None

    async def list_tasks(self, *, limit=100, control=None, from_time=None, to_time=None, cursor=None):
        return []

    async def list_observations(self, task_id):
        return []


def create_sql_ansich_service(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    queue_capacity: int = 10_000,
    queue_byte_capacity: int = 64 * 1024 * 1024,
    batch_size: int = 100,
    flush_interval_ms: int = 100,
    terminal_flush_timeout_ms: int = 2_000,
    projector_poll_interval_ms: int = 250,
    operations_assessment_interval_ms: int = 1_000,
    projector_lease_seconds: int = 30,
    projector_max_attempts: int = 5,
    projector_dependency_timeout_seconds: int = 300,
    inline_payload_max_bytes: int = 65_536,
    heartbeat_stale_after_seconds: int = 30,
    long_dwell_seconds: int = 120,
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
        ),
        queue_capacity=queue_capacity,
        queue_byte_capacity=queue_byte_capacity,
        batch_size=batch_size,
        flush_interval_ms=flush_interval_ms,
        terminal_flush_timeout_ms=terminal_flush_timeout_ms,
        projector_poll_interval_ms=projector_poll_interval_ms,
        operations_assessment_interval_ms=operations_assessment_interval_ms,
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
        projector_lease_seconds=config.projector_lease_seconds,
        projector_max_attempts=config.projector_max_attempts,
        projector_dependency_timeout_seconds=config.projector_dependency_timeout_seconds,
        inline_payload_max_bytes=config.inline_payload_max_bytes,
        heartbeat_stale_after_seconds=config.heartbeat_stale_after_seconds,
        long_dwell_seconds=config.long_dwell_seconds,
    )


__all__ = ["create_embedded_ansich_service", "create_sql_ansich_service"]

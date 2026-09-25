"""The extension's own tables, under its own metadata and ``ctxres_`` prefix.

Declared in the ``plugins:`` record as ``table_prefix: ctxres_`` so the host's
``alembic revision --autogenerate`` leaves them alone. Timestamps are ISO-8601
UTC strings: they compare and sort identically on SQLite and PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, Index, Integer, MetaData, String, Table

metadata = MetaData()

tasks = Table(
    "ctxres_tasks",
    metadata,
    Column("task_id", String(128), primary_key=True),
    Column("run_id", String(128), nullable=False),
    Column("thread_id", String(128), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("parent_task_id", String(128), nullable=True),
    Column("agent_name", String(256), nullable=True),
    Column("started_at", String(40), nullable=False),
    Column("stopped_at", String(40), nullable=True),
    Column("outcome", String(16), nullable=True),
    Index("ix_ctxres_tasks_thread", "thread_id", "started_at"),
)

attempts = Table(
    "ctxres_attempts",
    metadata,
    Column("attempt_id", String(64), primary_key=True),
    Column("task_id", String(128), nullable=False),
    Column("step_id", String(64), nullable=False),
    Column("step_seq", Integer, nullable=False),
    Column("attempt_no", Integer, nullable=False),
    Column("effective", Boolean, nullable=False, default=False),
    Column("status", String(16), nullable=False),
    Column("outcome", String(16), nullable=True),
    Column("occurred_at", String(40), nullable=False),
    Column("finished_at", String(40), nullable=True),
    Column("model_name", String(256), nullable=True),
    Column("message_count", Integer, nullable=False),
    Column("tool_schema_count", Integer, nullable=False),
    Column("visible_bytes", Integer, nullable=False),
    Column("estimated_tokens", Integer, nullable=False),
    Column("estimator_name", String(64), nullable=False),
    Column("estimator_version", String(16), nullable=False),
    Column("context_window_tokens", Integer, nullable=True),
    Index("ix_ctxres_attempts_task_order", "task_id", "step_seq", "attempt_no"),
)

members = Table(
    "ctxres_members",
    metadata,
    Column("attempt_id", String(64), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("block_id", String(64), nullable=False),
    Column("channel", String(16), nullable=False),
    Column("role", String(16), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("name", String(256), nullable=True),
    Column("content_hash", String(64), nullable=False),
    Column("source_identity", String(256), nullable=True),
    Column("summary_content_hash", String(64), nullable=True),
    Column("visible_bytes", Integer, nullable=False),
    Column("estimated_tokens", Integer, nullable=False),
    Index("ix_ctxres_members_block", "block_id", "attempt_id"),
)

compactions = Table(
    "ctxres_compactions",
    metadata,
    Column("compaction_id", String(64), primary_key=True),
    Column("task_id", String(128), nullable=True),
    Column("run_id", String(128), nullable=True),
    Column("thread_id", String(128), nullable=True),
    Column("transform_kind", String(64), nullable=False),
    Column("transform_version", String(16), nullable=False),
    Column("output_hash", String(64), nullable=False),
    Column("source_hashes", JSON, nullable=False),
    Column("kept_hashes", JSON, nullable=False),
    Column("compacted_count", Integer, nullable=False),
    Column("kept_count", Integer, nullable=False),
    Column("emitted_at", String(40), nullable=False),
    Column("observed_at", String(40), nullable=False),
    Index("ix_ctxres_compactions_task", "task_id", "emitted_at"),
)

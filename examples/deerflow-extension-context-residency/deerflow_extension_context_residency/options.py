"""Deployment configuration, from the ``plugins:`` record's ``config``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    #: Attempts returned per task read. The earliest attempts are kept and the
    #: response says explicitly that it was cut; nothing is capped silently.
    max_attempts: int = Field(500, ge=1, le=5000)
    #: Events buffered between writer flushes. A full buffer drops the event and
    #: counts it: a model-call hook must never block the turn on storage.
    queue_capacity: int = Field(20_000, ge=100, le=1_000_000)
    flush_interval_ms: int = Field(100, ge=10, le=5_000)
    #: Context window sizes by configured model name or provider model id, used
    #: when the host's model config declares no ``context_window`` for the model
    #: a request ran on; ``default_context_window`` covers everything else. An
    #: unknown window is recorded as absent, never guessed.
    context_windows: dict[str, int] = Field(default_factory=dict)
    default_context_window: int | None = Field(None, ge=1)
    #: A task with no stop event after this long counts as stale in the health view.
    stale_task_after_minutes: int = Field(60, ge=1, le=100_000)

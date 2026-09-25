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

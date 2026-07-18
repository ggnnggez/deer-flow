from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ansich.lineage import ContentBlockView

CompressionDisposition = Literal["source", "preserved", "removed"]


class ContextCompressionItemView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: CompressionDisposition
    ordinal: int
    block: ContentBlockView


class ContextCompressionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    compression_id: str
    task_id: str
    summary_operation_id: str | None
    summary_block: ContentBlockView
    before_tokens: int
    after_tokens: int
    before_visible_bytes: int
    after_visible_bytes: int
    algorithm: str
    algorithm_version: str
    source_obs_id: str
    status: Literal["complete", "incomplete"]
    items: tuple[ContextCompressionItemView, ...]


class ContextCompressionSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    compression_id: str
    task_id: str
    summary_operation_id: str | None
    summary_block_id: str
    before_tokens: int
    after_tokens: int
    before_visible_bytes: int
    after_visible_bytes: int
    algorithm: str
    algorithm_version: str
    source_obs_id: str
    occurred_at: datetime
    status: Literal["complete", "incomplete"]

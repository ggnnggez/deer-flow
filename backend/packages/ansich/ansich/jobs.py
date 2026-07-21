from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

FailedJobKind = Literal["projection", "assessor"]


class FailedJobSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    job_id: str
    kind: FailedJobKind
    name: str
    version: str
    task_id: str
    status: str
    attempts: int
    last_error: str | None = None
    available_at: datetime


class FailedJobErrorView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    attempt: int
    error_type: str
    message: str
    occurred_at: datetime


class FailedJobDetailView(FailedJobSummaryView):
    errors: tuple[FailedJobErrorView, ...]

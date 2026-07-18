from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class OperatorActionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_id: str
    task_id: str
    action_type: Literal["interrupt", "rollback"]
    idempotency_key: str
    status: Literal["requested", "succeeded", "failed"]
    requested_obs_id: str | None = None
    terminal_obs_id: str | None = None
    result: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime


class TaskActionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    source_kind: str
    run_id: str
    thread_id: str | None = None
    control_value: str

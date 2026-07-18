from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskHeartbeatView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: str
    heartbeat_obs_id: str
    occurred_at: datetime
    producer_instance_id: str
    ownership_epoch: str
    elapsed_ms: int = Field(ge=0)

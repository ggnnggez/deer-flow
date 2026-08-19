from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

EnvironmentScopeKind = Literal["container", "process_group", "host_shared"]
EnvironmentCoverage = Literal["continuous", "per_command", "uninstrumented"]

_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EnvironmentMetric(_FrozenModel):
    value: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=0)


class EnvironmentWindow(_FrozenModel):
    started_at: datetime
    ended_at: datetime
    sample_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_window(self) -> Self:
        if self.ended_at < self.started_at:
            raise ValueError("environment window ended_at must not precede started_at")
        return self


class EnvironmentSamplePayload(_FrozenModel):
    environment_scope: EnvironmentScopeKind
    coverage: EnvironmentCoverage
    window: EnvironmentWindow
    provider: str = Field(min_length=1, max_length=64)
    metrics: dict[str, EnvironmentMetric] = Field(default_factory=dict)
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def _validate_marks(self) -> Self:
        for name in self.metrics:
            if not _METRIC_NAME.match(name):
                raise ValueError(f"environment metric name is not canonical: {name!r}")
        if self.coverage == "uninstrumented":
            if self.metrics:
                raise ValueError("uninstrumented environment sample must not carry metrics")
            if self.window.sample_count != 0:
                raise ValueError("uninstrumented environment sample must declare sample_count=0")
        elif not self.metrics:
            raise ValueError("instrumented environment sample requires at least one metric")
        if self.coverage == "per_command":
            if self.tool_call_id is None:
                raise ValueError("per_command environment sample requires tool_call_id")
            if self.environment_scope != "process_group":
                raise ValueError("per_command environment sample must be process_group scoped")
        elif self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid for per_command coverage")
        return self

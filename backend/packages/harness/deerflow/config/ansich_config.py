from typing import Self

from pydantic import BaseModel, Field, model_validator


class AnsichAssessorConfig(BaseModel):
    """Versioned rule thresholds consumed by durable assessor jobs."""

    exact_repetition_window: int = Field(default=5, ge=2)
    tool_frequency_window_seconds: int = Field(default=300, ge=1)
    tool_frequency_threshold: int = Field(default=30, ge=1)


class AnsichConfig(BaseModel):
    """Restart-required configuration for the embedded Ansich service."""

    enabled: bool = Field(default=False, description="Enable embedded Ansich collection and developer/operator APIs.")
    queue_capacity: int = Field(default=10_000, ge=1, description="Maximum in-process observations waiting for persistence.")
    queue_byte_capacity: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        description="Maximum canonical serialized bytes held in the in-process observation queue.",
    )
    batch_size: int = Field(default=100, ge=1, description="Maximum observations written in one storage batch.")
    flush_interval_ms: int = Field(default=100, ge=1, description="Maximum delay before the writer flushes a partial batch.")
    terminal_flush_timeout_ms: int = Field(default=2_000, ge=1, description="Maximum terminal Task flush wait; timeout never fails the DeerFlow Run.")
    projector_poll_interval_ms: int = Field(default=250, ge=1, description="Polling interval for pending projection jobs.")
    projector_lease_seconds: int = Field(default=30, ge=1, description="Lease duration for a claimed projection job.")
    projector_max_attempts: int = Field(default=5, ge=1, description="Maximum projection attempts before a job is marked failed.")
    projector_dependency_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Maximum time a projection job may wait for a replay-safe dependency before it is marked failed.",
    )
    inline_payload_max_bytes: int = Field(
        default=65_536,
        ge=1,
        description="Largest canonical JSON Observation payload stored inline before using ansich_payloads.",
    )
    heartbeat_interval_seconds: int = Field(
        default=10,
        ge=1,
        description="Interval between outer Run worker liveness observations.",
    )
    heartbeat_stale_after_seconds: int = Field(
        default=30,
        ge=1,
        description="Age after which the heartbeat assessor may judge a running Task stale.",
    )
    long_dwell_seconds: int = Field(
        default=120,
        ge=1,
        description="Dwell threshold used by the operator-facing Task assessor.",
    )
    assessors: AnsichAssessorConfig = Field(
        default_factory=AnsichAssessorConfig,
        description="Versioned runaway and frequency assessor thresholds.",
    )

    @model_validator(mode="after")
    def _validate_heartbeat_window(self) -> Self:
        if self.heartbeat_stale_after_seconds < 2 * self.heartbeat_interval_seconds:
            raise ValueError("heartbeat_stale_after_seconds must be at least twice heartbeat_interval_seconds")
        return self

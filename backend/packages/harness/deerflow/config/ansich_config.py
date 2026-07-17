from pydantic import BaseModel, Field


class AnsichConfig(BaseModel):
    """Restart-required configuration for the embedded Ansich service."""

    enabled: bool = Field(default=False, description="Enable embedded Ansich collection and developer/operator APIs.")
    queue_capacity: int = Field(default=10_000, ge=1, description="Maximum in-process observations waiting for persistence.")
    batch_size: int = Field(default=100, ge=1, description="Maximum observations written in one storage batch.")
    flush_interval_ms: int = Field(default=100, ge=1, description="Maximum delay before the writer flushes a partial batch.")
    terminal_flush_timeout_ms: int = Field(default=2_000, ge=1, description="Maximum terminal Task flush wait; timeout never fails the DeerFlow Run.")
    projector_poll_interval_ms: int = Field(default=250, ge=1, description="Polling interval for pending projection jobs.")
    projector_lease_seconds: int = Field(default=30, ge=1, description="Lease duration for a claimed projection job.")
    projector_max_attempts: int = Field(default=5, ge=1, description="Maximum projection attempts before a job is marked failed.")
    inline_payload_max_bytes: int = Field(
        default=65_536,
        ge=1,
        description="Largest canonical JSON Observation payload stored inline before using ansich_payloads.",
    )

from typing import Self

from pydantic import BaseModel, Field, model_validator


class AnsichAssessorConfig(BaseModel):
    """Versioned rule thresholds consumed by durable assessor jobs."""

    exact_repetition_window: int = Field(default=5, ge=2)
    tool_frequency_window_seconds: int = Field(default=300, ge=1)
    tool_frequency_threshold: int = Field(default=30, ge=1)
    environment_fd_warn_ratio: float = Field(default=0.8, gt=0, le=1)
    environment_fd_critical_ratio: float = Field(default=0.95, gt=0, le=1)
    environment_disk_free_warn_ratio: float = Field(default=0.10, gt=0, le=1)
    environment_disk_free_critical_ratio: float = Field(default=0.05, gt=0, le=1)
    environment_psi_warn_milli: int = Field(default=40000, ge=1)
    environment_psi_critical_milli: int = Field(default=80000, ge=1)
    environment_leak_min_samples: int = Field(default=6, ge=1)
    environment_leak_window_seconds: int = Field(default=60, ge=1)
    environment_leak_min_growth: int = Field(default=50, ge=1)

    @model_validator(mode="after")
    def _validate_environment_thresholds(self) -> Self:
        if self.environment_fd_warn_ratio >= self.environment_fd_critical_ratio:
            raise ValueError("environment_fd_warn_ratio must be less than environment_fd_critical_ratio")
        if self.environment_psi_warn_milli >= self.environment_psi_critical_milli:
            raise ValueError("environment_psi_warn_milli must be less than environment_psi_critical_milli")
        if self.environment_disk_free_critical_ratio >= self.environment_disk_free_warn_ratio:
            raise ValueError("environment_disk_free_critical_ratio must be less than environment_disk_free_warn_ratio")
        return self


class AnsichRetentionConfig(BaseModel):
    """Time-tiered retention policy for the Ansich store.

    Three tiers, each a maximum age in days, and one batch size. The tiers are
    nested rather than independent: raw payload bodies expire first, then the
    Observations that referenced them, and only then the structural Entity and
    Relation rows those Observations built. That containment is enforced by the
    validator below rather than left to the operator, because an inverted pair
    is not a stricter policy — it is a broken store. A payload that outlives
    its Observation is unreadable evidence kept at cost; a structural row that
    dies before its Observations leaves the dangling references the RESTRICT
    walls exist to prevent.

    Retention is executed in bounded batches (``cleanup_batch_size``) with a
    durable per-tier cursor, so a pass that is interrupted resumes where it
    stopped rather than restarting or skipping. There is no "disable" value
    here on purpose: zero is refused on every field because it would spell a
    switch as a bound (``raw_payload_days: 0`` means "delete evidence on
    arrival"; ``cleanup_batch_size: 0`` means a batch that deletes nothing and
    therefore never terminates).
    """

    raw_payload_days: int = Field(default=7, ge=1)
    observation_days: int = Field(default=30, ge=1)
    structural_days: int = Field(default=90, ge=1)
    cleanup_batch_size: int = Field(default=500, ge=1)

    @model_validator(mode="after")
    def _validate_tier_containment(self) -> Self:
        if self.raw_payload_days > self.observation_days:
            raise ValueError("raw_payload_days must not exceed observation_days")
        if self.observation_days > self.structural_days:
            raise ValueError("observation_days must not exceed structural_days")
        return self


class AnsichConfig(BaseModel):
    """Restart-required configuration for the embedded Ansich service.

    The whole ``ansich`` section is registered restart-required in
    ``deerflow.config.reload_boundary.STARTUP_ONLY_FIELDS``, so **every** field
    below carries the standardised ``startup-only:`` marker. The prefix is not
    decoration: it is the token IDE hover and any future "needs restart"
    scanner pivot on, and a field missing it reads as hot-reloadable while its
    neighbours do not.
    """

    enabled: bool = Field(default=False, description="startup-only: Enable embedded Ansich collection and developer/operator APIs.")
    queue_capacity: int = Field(default=10_000, ge=1, description="startup-only: Maximum in-process observations waiting for persistence.")
    queue_byte_capacity: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        description="startup-only: Maximum canonical serialized bytes held in the in-process observation queue.",
    )
    batch_size: int = Field(default=100, ge=1, description="startup-only: Maximum observations written in one storage batch.")
    flush_interval_ms: int = Field(default=100, ge=1, description="startup-only: Maximum delay before the writer flushes a partial batch.")
    terminal_flush_timeout_ms: int = Field(default=2_000, ge=1, description="startup-only: Maximum terminal Task flush wait; timeout never fails the DeerFlow Run.")
    projector_poll_interval_ms: int = Field(default=250, ge=1, description="startup-only: Polling interval for pending projection jobs.")
    operations_assessment_interval_ms: int = Field(
        default=1_000,
        ge=1,
        description="startup-only: Interval between periodic operations assessment passes (heartbeat/dwell/budget/environment/process alerts).",
    )
    health_database_timeout_ms: int = Field(
        default=2_000,
        ge=1,
        description=(
            "startup-only: budget for the database half of the Ansich health read. Past it the response "
            "carries database.status=unreachable and the process-side health fields are served unchanged, "
            "so a stalled store costs a bounded wait rather than the health endpoint."
        ),
    )
    projector_lease_seconds: int = Field(default=30, ge=1, description="startup-only: Lease duration for a claimed projection job.")
    projector_max_attempts: int = Field(default=5, ge=1, description="startup-only: Maximum projection attempts before a job is marked failed.")
    projector_dependency_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="startup-only: Maximum time a projection job may wait for a replay-safe dependency before it is marked failed.",
    )
    inline_payload_max_bytes: int = Field(
        default=65_536,
        ge=1,
        description="startup-only: Largest canonical JSON Observation payload stored inline before using ansich_payloads.",
    )
    writer_retry_max_attempts: int = Field(
        default=5,
        ge=1,
        description="startup-only: attempts the writer makes on one refused batch before isolating it item by item.",
    )
    writer_backoff_initial_ms: int = Field(
        default=100,
        ge=1,
        description="startup-only: first delay the writer waits after a refused batch; doubles per attempt.",
    )
    writer_backoff_max_ms: int = Field(
        default=5_000,
        ge=1,
        description="startup-only: ceiling for the writer's doubling retry delay.",
    )
    writer_item_max_attempts: int = Field(
        default=2,
        ge=1,
        description="startup-only: attempts one Observation gets during item-by-item isolation before it is judged poison.",
    )
    stop_drain_timeout_ms: int = Field(
        default=10_000,
        ge=1,
        description=(
            "startup-only: total budget for the writer's drain at collector stop. It bounds the in-flight "
            "attempt itself — the drain cancels a persist that has not returned — not merely the queued "
            "backlog or a number of retries, so a wedged storage call cannot hold shutdown open. Whatever "
            "the drain could not place by then is charged as lost and reported in one warning. "
            "CLAMPED BY shutdown_budget_ms: the drain is one step of the shutdown sequence and takes the "
            "smaller of this value and its share of that budget (0.4 of it, so 2s at the 5s default), which "
            "means a value above that share is INERT during shutdown. Raising this alone changes nothing; "
            "raise shutdown_budget_ms — and the pod's grace period — with it."
        ),
    )
    shutdown_budget_ms: int = Field(
        default=5_000,
        ge=1,
        description=(
            "startup-only: total budget for the collector's whole shutdown sequence (spec 11 section 8): "
            "stop recording, stop this service's own timers, finish outstanding terminal barriers, drain "
            "the writer, stop claiming new projection work, join the projector, and write the process-wide "
            "loss bucket down. Each step takes the smaller of its own share and what is left, and a step "
            "that times out does not stop the ones after it. "
            "The 5s default is what the Gateway's SERIAL shutdown leaves: this sequence runs LAST, in the "
            "langgraph_runtime context manager's finally, after the other BUDGETED terms -- preStop sleep "
            "(5s) + channel stop (5s) + browser sessions (5s) + memory flush "
            "(memory.shutdown_flush_timeout_seconds, 30s) + in-flight run drain (5s) = 50s -- against the "
            "gateway chart's terminationGracePeriodSeconds of 60s. Those five plus this one are the terms "
            "that carry a bound, not the whole list: the scheduled-task service stop is UNBOUNDED (no "
            "timeout at its call site), and closing the OIDC service and the database engine are unbudgeted "
            "too, which is part of what the remaining buffer is for. This step itself can also run up to "
            "0.25s past its budget (five per-step graces of 50ms). A larger budget here is only honoured if "
            "the pod's grace period is raised with it, because SIGKILL landing mid-sequence would lose the "
            "process-loss bucket this sequence exists to write down -- and the report saying so with it."
        ),
    )
    heartbeat_interval_seconds: int = Field(
        default=10,
        ge=1,
        description="startup-only: Interval between outer Run worker liveness observations.",
    )
    heartbeat_stale_after_seconds: int = Field(
        default=30,
        ge=1,
        description="startup-only: Age after which the heartbeat assessor may judge a running Task stale.",
    )
    long_dwell_seconds: int = Field(
        default=120,
        ge=1,
        description="startup-only: Dwell threshold used by the operator-facing Task assessor.",
    )
    evaluation_min_cohort_samples: int = Field(
        default=5,
        ge=1,
        description="startup-only: Assessed samples required on both sides before a release quality cohort is comparable.",
    )
    evaluation_max_payload_bytes: int = Field(
        default=262_144,
        ge=1,
        description="startup-only: Largest accepted evaluation record payload; larger submissions are rejected rather than truncated.",
    )
    raw_read_max_bytes: int = Field(
        default=1_048_576,
        ge=1,
        description="startup-only: Approximate bound on the raw payload body one audited admin read may return; a larger body is refused with 413 and audited. Measured on the payload document, not the response envelope.",
    )
    environment_probe_enabled: bool = Field(
        default=True,
        description="startup-only: Enable environment probe collection.",
    )
    environment_sample_interval_seconds: int | None = Field(
        default=None,
        ge=1,
        description="startup-only: Interval for environment sampling; None uses heartbeat_interval_seconds.",
    )
    environment_per_command_sampling: bool = Field(
        default=True,
        description="startup-only: Enable per-command environment sampling.",
    )
    assessors: AnsichAssessorConfig = Field(
        default_factory=AnsichAssessorConfig,
        description="startup-only: Versioned runaway and frequency assessor thresholds.",
    )
    retention: AnsichRetentionConfig = Field(
        default_factory=AnsichRetentionConfig,
        description="startup-only: Time-tiered retention policy — raw payload bodies, then Observations, then structural rows.",
    )

    @property
    def effective_environment_sample_interval_seconds(self) -> int:
        return self.environment_sample_interval_seconds or self.heartbeat_interval_seconds

    @model_validator(mode="after")
    def _validate_heartbeat_window(self) -> Self:
        if self.heartbeat_stale_after_seconds < 2 * self.heartbeat_interval_seconds:
            raise ValueError("heartbeat_stale_after_seconds must be at least twice heartbeat_interval_seconds")
        return self

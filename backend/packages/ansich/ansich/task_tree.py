from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ansich.contracts import TaskView
from ansich.operations import ActiveStepView, HeartbeatBelief
from ansich.release import TaskAgentReleaseView
from ansich.usage import TaskUsageView

TaskTreeDirection = Literal["ancestors", "descendants", "both"]


class TaskSpawnView(BaseModel):
    """Typed evidence that one parent ToolCall established a child Task."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    parent_task_id: str
    spawning_step_id: str
    spawning_tool_call_id: str
    child_task_id: str
    established_obs_id: str
    subagent_name: str | None = None


class TaskAncestryView(BaseModel):
    """One self-free row in the Task transitive closure."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ancestor_task_id: str
    descendant_task_id: str
    depth: int
    established_obs_id: str


class TaskTreeNodeView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task: TaskView
    agent_release: TaskAgentReleaseView | None = None
    heartbeat: HeartbeatBelief | None = None
    current_step: ActiveStepView | None = None
    usage: TaskUsageView


class TaskTreeView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    root_task_id: str
    direction: TaskTreeDirection
    depth: int = Field(ge=1, le=32)
    nodes: tuple[TaskTreeNodeView, ...]
    edges: tuple[TaskSpawnView, ...]
    truncated: bool

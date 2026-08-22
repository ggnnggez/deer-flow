from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

#: Operator actions that target one Task and own a durable
#: ``ansich_operator_actions`` row: the request is idempotency-keyed, elected,
#: and terminalized, and the row is what a retry replays.
TaskOperatorActionType = Literal["interrupt", "rollback"]

#: Operator actions that target the **process**, not a Task, and therefore own
#: no ledger row: their whole record is the audit Observation. They are carried
#: in that Observation's ``payload["action_type"]`` under the same
#: ``operator.action_*`` kinds, which is what makes one audit read find both
#: families.
#:
#: The split is not cosmetic. A member of this family has no ``task_id`` to be
#: keyed by, no concurrent-request election to win, and nothing for a retry to
#: replay — putting it in :data:`TaskOperatorActionType` would widen
#: :class:`OperatorActionView` (whose ``task_id`` is required) into a shape no
#: row can ever have. RC8's discriminator machinery is a separate concern and
#: is not required to add a member here.
#:
#: ``activate_version`` is an audited active-version switch, written by
#: ``activate_version()`` in the SQL backend. ``raw_payload_read`` is one
#: admin read of one raw body through the four §7 endpoints, written by
#: ``record_raw_read_audit()`` beside it.
#:
#: **Both members are subjected the same way** (RC8, unified): the owning Task
#: when the thing read belongs to one, else the host ``Scope`` when this store
#: has one, else ``ANSICH_BOOTSTRAP_TASK_ID``. The envelope validator's
#: Scope arm admits a Scope subject for exactly this family and refuses it for
#: :data:`TaskOperatorActionType`, whose members always have a Task.
OperatorAuditActionType = Literal["activate_version", "raw_payload_read"]

#: The audited read of one raw payload body (§7). Annotated rather than written
#: as a bare string at the two write sites, so the Literal above does
#: structural work: a test asserts the value that lands in the payload is one
#: of its members.
RAW_PAYLOAD_READ_ACTION: OperatorAuditActionType = "raw_payload_read"


class OperatorActionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_id: str
    task_id: str
    action_type: TaskOperatorActionType
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

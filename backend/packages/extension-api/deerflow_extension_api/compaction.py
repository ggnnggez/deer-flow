"""The transform that replaces many messages with one.

Summarization is destructive by design: N messages leave the context and one
summary enters it. Afterwards only the summary exists, so nothing downstream can
answer "which messages became this?" — the mapping is gone. It has to be emitted
where it is still true.

Fields are keyed on canonical content hashes (``deerflow_extension_api.canonical_hash``),
not a producer-stamped identity key: nothing in the host currently mints a stable
per-message identity for the messages a compaction consumes or the summary it
produces, so an identity-keyed field would ship permanently empty in every event.
Every message has content, so hashing it is always available.

The exact recipe both sides must use: ``canonical_hash(message.content)`` — the
message's ``content`` attribute passed directly, never pre-stringified. DeerFlow
messages are routinely multimodal (``list[dict]`` content), and ``str()`` on a
dict renders insertion order, so two logically identical messages would hash
differently if stringified first. ``canonical_hash`` already normalizes through
``canonical_json`` (sorted keys, deterministic separators); passing it anything
else throws that normalization away.

Trap for consumers: ``DurableContextMiddleware`` is the only place the produced summary
text later reaches a message (the ``durable_context_data`` block), but
``_render_durable_context_data`` renders a *bounded, HTML-escaped* projection of
``summary_text`` for the model prompt, not the summary itself. Hashing that rendering
will not equal ``output_content_hash``. A consumer must join a compaction to what came
after it through this event alone, never by re-hashing a later projection of the same
text.

The event also names the task it happened in. Compaction observers are notified
outside the turn and receive a detached store, so an observer keeping per-task
records (a context ledger, a residency matrix) could not otherwise tell whose
context just shrank. ``task_id`` / ``run_id`` / ``thread_id`` are copied from the
emitting task's ``TaskInfo`` — the identity ``on_task_start`` reported, which the
host seeds into every task store — and stay ``None`` when the emitting runtime
carries no seeded store; the host never substitutes a run id for a subagent's task
id. ``emitted_at`` is the host's UTC wall-clock time taken synchronously at
emission, before the notification is dispatched, so an observer can order the
event against records it timestamped itself on the same host even though the
notification arrives asynchronously.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from deerflow_extension_api.state import ExtensionData


@dataclass(frozen=True)
class CompactionEvent:
    """What a compaction consumed and produced, captured while both still exist."""

    transform_kind: str
    transform_version: str
    source_content_hashes: tuple[str, ...]
    output_content_hash: str
    compacted_message_count: int
    kept_message_count: int
    #: ``canonical_hash(message.content)`` for each message that survived the
    #: compaction, in order — captured at the same moment as the sources. Empty
    #: when no observer was registered at freeze time (the host skips the hashing
    #: pass) and on events from a host older than this field.
    kept_content_hashes: tuple[str, ...] = ()
    #: The compacted task's identity, from its ``TaskInfo``; ``None`` when the
    #: emitting runtime carried no seeded task store.
    task_id: str | None = None
    run_id: str | None = None
    thread_id: str | None = None
    #: ISO-8601 UTC timestamp taken at emission, before dispatch.
    emitted_at: str | None = None


class ContextCompactionObserver(Protocol):
    async def on_context_compacted(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        event: CompactionEvent,
    ) -> None:
        return None

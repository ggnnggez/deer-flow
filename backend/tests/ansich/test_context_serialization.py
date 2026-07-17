from __future__ import annotations

from types import SimpleNamespace

from ansich.serialization import serialize_model_request
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel


class _StructuredAnswer(BaseModel):
    answer: str


@tool
def _search(query: str, limit: int = 5) -> str:
    """Search a bounded corpus."""
    return f"{query}:{limit}"


def test_snapshot_preserves_message_and_content_part_occurrence_order() -> None:
    capture = serialize_model_request(
        system_message=SystemMessage(content="rules"),
        messages=[
            HumanMessage(
                id="human-1",
                content=[
                    {"type": "text", "text": "same"},
                    {"type": "image_url", "image_url": {"url": "artifact://image-1"}},
                ],
            ),
            AIMessage(
                id="ai-1",
                content="same",
                tool_calls=[{"id": "provider-call-1", "name": "search", "args": {"q": "deer"}}],
            ),
            ToolMessage(id="tool-1", tool_call_id="provider-call-1", content="found"),
        ],
        tools=[],
        response_format=None,
        model_settings={"temperature": 0.2},
        model=None,
    )

    assert [(item.ordinal, item.channel, item.role, item.block.kind) for item in capture.items] == [
        (0, "message", "system", "system_prompt"),
        (1, "message", "user", "user_input"),
        (2, "message", "user", "image_or_attachment"),
        (3, "message", "assistant", "assistant_output"),
        (4, "message", "assistant", "tool_request"),
        (5, "message", "tool", "tool_result_visible"),
    ]
    repeated = [item.block for item in capture.items if item.block.body == "same"]
    assert len(repeated) == 2
    assert repeated[0].content_hash == repeated[1].content_hash
    assert repeated[0].block_id != repeated[1].block_id
    assert capture.message_count == 4
    assert capture.generation_settings == {"temperature": 0.2}


def test_snapshot_structurally_excludes_secret_fields_and_redacts_known_values() -> None:
    secret = "request-secret-value"
    capture = serialize_model_request(
        system_message=None,
        messages=[
            HumanMessage(
                content=[
                    {
                        "type": "input_text",
                        "question": "safe",
                        "authorization": "Bearer should-never-land",
                        "nested": {"value": secret},
                    }
                ]
            )
        ],
        tools=[
            {
                "name": "remote",
                "description": "safe",
                "headers": {"X-Api-Key": "also-secret"},
            }
        ],
        response_format=None,
        model_settings={"extra_body": {"cookie": "session-secret", "safe": secret}},
        model=None,
        known_secrets=[secret],
    )

    serialized = capture.model_dump(mode="json")
    rendered = str(serialized)
    assert "should-never-land" not in rendered
    assert "also-secret" not in rendered
    assert "session-secret" not in rendered
    assert secret not in rendered
    assert "<redacted>" in rendered
    assert [entry.reason for entry in capture.redactions] == [
        "secret_field",
        "known_secret_value",
        "secret_field",
        "secret_field",
        "known_secret_value",
    ]


def test_snapshot_keeps_unsupported_values_without_calling_repr() -> None:
    class DangerousValue:
        def __repr__(self) -> str:
            raise AssertionError("serializer must not call repr")

    capture = serialize_model_request(
        system_message=None,
        messages=[SimpleNamespace(type="human", id="human-1", name=None, content=[DangerousValue()])],
        tools=[],
        response_format=None,
        model_settings={},
        model=None,
    )

    assert capture.items[0].block.kind == "user_input"
    assert capture.items[0].block.body == {
        "type": f"{DangerousValue.__module__}.{DangerousValue.__name__}",
        "status": "unsupported",
    }
    assert capture.warnings == (f"messages[0].content[0]:unsupported:{DangerousValue.__module__}.{DangerousValue.__name__}",)


def test_snapshot_captures_visible_tool_and_response_schemas() -> None:
    _search.metadata = {"deferred": True, "source": "mcp:catalog"}
    capture = serialize_model_request(
        system_message=None,
        messages=[HumanMessage(content="find deer")],
        tools=[_search],
        response_format=_StructuredAnswer,
        model_settings={"top_p": 0.8, "unrelated_internal_setting": "ignored"},
        model=None,
    )

    tool_item = capture.items[-1]
    assert tool_item.channel == "tool_schema"
    assert tool_item.name == "_search"
    assert tool_item.block.body["description"] == "Search a bounded corpus."
    assert tool_item.block.body["argument_schema"]["properties"]["query"]["type"] == "string"
    assert tool_item.block.body["metadata"] == {"deferred": True, "source": "mcp:catalog"}
    assert capture.response_format["properties"]["answer"]["type"] == "string"
    assert capture.generation_settings == {"top_p": 0.8}


def test_attachment_capture_keeps_controlled_artifact_identity_but_omits_signed_urls() -> None:
    signed_url = "https://provider.example/image.png?signature=top-secret"
    capture = serialize_model_request(
        system_message=None,
        messages=[
            HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": signed_url}, "detail": "high"},
                    {
                        "type": "attachment",
                        "artifact_id": "artifact-42",
                        "mime_type": "image/png",
                        "width": 640,
                        "height": 480,
                    },
                ]
            )
        ],
        tools=[],
        response_format=None,
        model_settings={},
        model=None,
    )

    rendered = str(capture.model_dump(mode="json"))
    assert signed_url not in rendered
    assert capture.items[0].block.body == {
        "type": "image_url",
        "detail": "high",
        "reference_status": "omitted_external_or_embedded_reference",
    }
    assert capture.items[1].block.body["artifact_id"] == "artifact-42"
    assert capture.redactions[0].reason == "credential_bearing_reference"

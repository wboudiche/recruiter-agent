import json

from recruiter.agent.events import (
    error_event,
    message_done_event,
    message_event,
    message_delta_event,
    serialize_event,
    tool_call_result_event,
    tool_call_start_event,
)


def _parse(line: str) -> dict:
    assert line.endswith("\n")
    return json.loads(line)


def test_message_event_serializes_with_newline() -> None:
    line = serialize_event(message_event(role="user", id=42, content="hi"))
    parsed = _parse(line)
    assert parsed == {"type": "message", "role": "user", "id": 42, "content": "hi"}


def test_tool_call_start_event() -> None:
    parsed = _parse(serialize_event(
        tool_call_start_event(id="tc_1", name="get_candidate", arguments={"x": 1})
    ))
    assert parsed == {"type": "tool_call_start", "id": "tc_1", "name": "get_candidate",
                      "arguments": {"x": 1}}


def test_tool_call_result_event() -> None:
    parsed = _parse(serialize_event(
        tool_call_result_event(id="tc_1", name="get_candidate", result={"full_name": "Marie"})
    ))
    assert parsed == {"type": "tool_call_result", "id": "tc_1", "name": "get_candidate",
                      "result": {"full_name": "Marie"}}


def test_message_delta_event() -> None:
    parsed = _parse(serialize_event(message_delta_event(text="hi there")))
    assert parsed == {"type": "message_delta", "text": "hi there"}


def test_message_done_event() -> None:
    parsed = _parse(serialize_event(message_done_event(id=99)))
    assert parsed == {"type": "message_done", "id": 99}


def test_error_event() -> None:
    parsed = _parse(serialize_event(error_event(detail="boom", phase="llm")))
    assert parsed == {"type": "error", "detail": "boom", "phase": "llm"}


def test_serialize_handles_unicode() -> None:
    line = serialize_event(message_delta_event(text="Marie Lefèvre"))
    assert "Marie Lefèvre" in line

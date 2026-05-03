import json
from typing import Any, Literal


def message_event(*, role: str, id: int, content: str | None) -> dict:
    return {"type": "message", "role": role, "id": id, "content": content}


def tool_call_start_event(*, id: str, name: str, arguments: dict) -> dict:
    return {"type": "tool_call_start", "id": id, "name": name, "arguments": arguments}


def tool_call_result_event(*, id: str, name: str, result: Any) -> dict:
    return {"type": "tool_call_result", "id": id, "name": name, "result": result}


def message_delta_event(*, text: str) -> dict:
    return {"type": "message_delta", "text": text}


def message_done_event(*, id: int) -> dict:
    return {"type": "message_done", "id": id}


def error_event(*, detail: str, phase: Literal["llm", "tool", "persist", "agent"]) -> dict:
    return {"type": "error", "detail": detail, "phase": phase}


def tool_search_results_event(
    *,
    tool_name: str,
    source: Literal["linkedin", "github", "web"],
    results: list[dict],
) -> dict:
    """Frontend-only event carrying structured search-result cards.
    NOT fed back to the LLM (the tool handler returns a text summary
    separately for that)."""
    return {
        "type": "tool.search_results",
        "tool_name": tool_name,
        "source": source,
        "results": results,
    }


def serialize_event(event: dict) -> str:
    """One JSON object per line, trailing newline; non-ASCII passes through."""
    return json.dumps(event, ensure_ascii=False) + "\n"

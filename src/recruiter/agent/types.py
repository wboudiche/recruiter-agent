from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict  # JSON Schema


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AssistantTurn:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ChatTurn:
    """One row of conversation history fed to chat_with_tools.

    role='user' | 'assistant' | 'tool'.
    For assistant turns with tool calls, content may be None and tool_calls is non-empty.
    For tool result turns, tool_call_id, tool_name, and tool_result must all be set.
    """
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None

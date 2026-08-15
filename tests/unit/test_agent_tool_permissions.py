"""Chat is allowlisted for viewers, so the write capability has to be
removed inside the agent.

`POST /applications/{id}/chat` looks conversational but carries three
mutating tools. A viewer reaching chat with those tools available could
validate and reject candidates by conversation, while
`PATCH /applications/{id}` is gated shut — a hole exactly as wide as the
route-level gate it bypasses.
"""

import pytest

from recruiter.agent.tools import (
    WRITE_TOOL_NAMES,
    ToolContext,
    get_tool_handler,
    tools_for,
)
from recruiter.models import Role


def test_viewer_is_offered_no_write_tools() -> None:
    names = {t.name for t in tools_for(Role.VIEWER)}

    assert names & WRITE_TOOL_NAMES == set()


def test_viewer_keeps_the_read_and_search_tools() -> None:
    """Withholding writes must not gut the feature: answering "why did
    this candidate score low?" is the reason viewers get chat at all."""
    names = {t.name for t in tools_for(Role.VIEWER)}

    assert {"get_candidate", "get_application", "get_score_breakdown"} <= names
    assert "search_web" in names


@pytest.mark.parametrize("role", [Role.RECRUITER, Role.ADMIN])
def test_recruiters_and_admins_keep_every_tool(role: Role) -> None:
    names = {t.name for t in tools_for(role)}

    assert WRITE_TOOL_NAMES <= names


@pytest.mark.parametrize("tool_name", sorted(WRITE_TOOL_NAMES))
@pytest.mark.asyncio
async def test_write_handlers_refuse_a_viewer_even_if_called_directly(
    tool_name: str, db_session_with_schema, monkeypatch,
) -> None:
    """The second layer, deliberately redundant. If a later refactor
    rebuilds the tool list and forgets the filter, the mutation must still
    not happen."""
    ctx = ToolContext(
        session=db_session_with_schema,
        application_id=1,
        undo_store={},
        role=Role.VIEWER,
    )
    handler = get_tool_handler(tool_name)

    with pytest.raises(PermissionError):
        await handler(ctx, {"text": "x", "reason": "x", "notes": "x"})

from recruiter.agent.tools import ToolContext


def test_tool_context_has_default_empty_frontend_events() -> None:
    ctx = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    assert ctx.frontend_events == []


def test_tool_context_frontend_events_is_independent_per_instance() -> None:
    ctx1 = ToolContext(session=None, application_id=1, undo_store=None)  # type: ignore[arg-type]
    ctx2 = ToolContext(session=None, application_id=2, undo_store=None)  # type: ignore[arg-type]
    ctx1.frontend_events.append({"x": 1})
    assert ctx2.frontend_events == []

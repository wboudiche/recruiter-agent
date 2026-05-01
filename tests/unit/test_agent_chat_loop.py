import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.chat import run_turn
from recruiter.agent.types import AssistantTurn, ToolCall
from recruiter.agent.undo import UndoStore
from recruiter.llm.client import FakeLLMClient
from recruiter.models import Application, Candidate, ChatMessage, Job, Stage


async def _seed_app(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job); await session.flush()
    candidate = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(candidate); await session.flush()
    app = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.SCORED, score=80)
    session.add(app); await session.commit()
    return app.id


async def _collect(generator):
    return [event async for event in generator]


@pytest.mark.asyncio
async def test_zero_tool_turn(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    fake = FakeLLMClient(tool_turn_responses=[
        AssistantTurn(text="Marie has strong async Rust experience.", tool_calls=[]),
    ])

    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="tell me about her", llm=fake, undo_store=UndoStore(),
    ))

    types = [e["type"] for e in events]
    assert types == ["message", "message_delta", "message_done"]
    assert events[0]["role"] == "user"
    assert events[1]["text"] == "Marie has strong async Rust experience."

    rows = (await db_session_with_schema.execute(
        ChatMessage.__table__.select().order_by(ChatMessage.id)
    )).all()
    assert len(rows) == 2  # user + assistant
    assert rows[0].role == "user" and rows[0].content == "tell me about her"
    assert rows[1].role == "assistant" and rows[1].content.startswith("Marie")


@pytest.mark.asyncio
async def test_one_tool_then_text(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    fake = FakeLLMClient(tool_turn_responses=[
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="get_candidate", arguments={}),
        ]),
        AssistantTurn(text="Her email is m@example.com.", tool_calls=[]),
    ])
    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="email?", llm=fake, undo_store=UndoStore(),
    ))
    types = [e["type"] for e in events]
    assert types == [
        "message", "tool_call_start", "tool_call_result",
        "message_delta", "message_done",
    ]
    assert events[2]["result"]["email"] == "m@example.com"


@pytest.mark.asyncio
async def test_tool_failure_is_non_terminal(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    fake = FakeLLMClient(tool_turn_responses=[
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="not_a_real_tool", arguments={}),
        ]),
        AssistantTurn(text="Sorry, that didn't work.", tool_calls=[]),
    ])
    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="?", llm=fake, undo_store=UndoStore(),
    ))
    # tool_call_result carries an error payload, but the turn still completes
    result_event = next(e for e in events if e["type"] == "tool_call_result")
    assert "error" in result_event["result"]
    assert events[-1]["type"] == "message_done"


@pytest.mark.asyncio
async def test_llm_exception_is_terminal(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)

    class Boom:
        async def chat_with_tools(self, *a, **kw):
            raise RuntimeError("api down")

    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="?", llm=Boom(), undo_store=UndoStore(),
    ))
    types = [e["type"] for e in events]
    assert types[-1] == "error"
    assert "message_done" not in types
    assert events[-1]["phase"] == "llm"
    assert "api down" in events[-1]["detail"]


@pytest.mark.asyncio
async def test_max_iterations_terminal(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    looping = [
        AssistantTurn(text=None, tool_calls=[ToolCall(id=f"t{i}", name="get_candidate", arguments={})])
        for i in range(20)
    ]
    fake = FakeLLMClient(tool_turn_responses=looping)
    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="loop", llm=fake, undo_store=UndoStore(),
        max_steps=3,
    ))
    err = events[-1]
    assert err["type"] == "error" and err["phase"] == "agent"
    assert "max iterations" in err["detail"].lower()


@pytest.mark.asyncio
async def test_validate_tool_through_loop(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    fake = FakeLLMClient(tool_turn_responses=[
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="validate_application", arguments={"notes": "looks great"}),
        ]),
        AssistantTurn(text="Validated.", tool_calls=[]),
    ])
    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="validate her", llm=fake, undo_store=UndoStore(),
    ))
    result_event = next(e for e in events if e["type"] == "tool_call_result")
    assert result_event["result"]["ok"] is True
    assert "undo_token" in result_event["result"]
    app = await db_session_with_schema.get(Application, app_id)
    assert app.stage.value == "validated"

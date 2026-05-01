import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, ChatMessage, Job, MessageRole, Stage


@pytest.mark.asyncio
async def test_chat_message_roundtrip(db_session_with_schema: AsyncSession) -> None:
    job = Job(title="Backend", description="Build APIs", criteria=[])
    db_session_with_schema.add(job)
    await db_session_with_schema.flush()
    candidate = Candidate(source_type="paste")
    db_session_with_schema.add(candidate)
    await db_session_with_schema.flush()
    app = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.SCORED)
    db_session_with_schema.add(app)
    await db_session_with_schema.flush()

    user_msg = ChatMessage(application_id=app.id, role=MessageRole.USER, content="hi")
    assistant_msg = ChatMessage(
        application_id=app.id,
        role=MessageRole.ASSISTANT,
        content=None,
        tool_calls=[{"id": "tc_1", "name": "get_candidate", "arguments": {}}],
    )
    tool_msg = ChatMessage(
        application_id=app.id,
        role=MessageRole.TOOL,
        tool_call_id="tc_1",
        tool_name="get_candidate",
        tool_result={"full_name": "Marie"},
    )
    db_session_with_schema.add_all([user_msg, assistant_msg, tool_msg])
    await db_session_with_schema.commit()

    fetched = (await db_session_with_schema.execute(
        ChatMessage.__table__.select().order_by(ChatMessage.id)
    )).all()
    assert len(fetched) == 3
    assert fetched[0].role == "user"
    assert fetched[1].tool_calls == [{"id": "tc_1", "name": "get_candidate", "arguments": {}}]
    assert fetched[2].tool_result == {"full_name": "Marie"}

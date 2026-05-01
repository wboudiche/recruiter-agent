from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.types import ToolDef
from recruiter.agent.undo import UndoStore, get_default_undo_store
from recruiter.models import Application, Candidate, Job, Stage

# Variadic over keyword args so write tools (validate/reject) which accept an
# extra `undo_store` keyword still satisfy the alias. The agent loop does the
# name-based dispatch; a future ToolContext refactor will collapse this.
ToolHandler = Callable[..., Awaitable[dict | list]]

_HANDLERS: dict[str, ToolHandler] = {}


def _register(name: str):
    def deco(fn: ToolHandler) -> ToolHandler:
        _HANDLERS[name] = fn
        return fn
    return deco


def get_tool_handler(name: str) -> ToolHandler:
    if name not in _HANDLERS:
        raise ValueError(f"unknown tool: {name}")
    return _HANDLERS[name]


@_register("get_candidate")
async def _get_candidate(session: AsyncSession, application_id: int, args: dict) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    candidate = await session.get(Candidate, app.candidate_id)
    if candidate is None:
        return {"error": "candidate not found"}
    return {
        "full_name": candidate.full_name,
        "email": candidate.email,
        "phone": candidate.phone,
        "location": candidate.location,
        "headline": candidate.headline,
        "summary": candidate.summary,
        "skills": candidate.skills or [],
        "experience": candidate.experience or [],
        "education": candidate.education or [],
        "links": candidate.links or [],
    }


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None else None


@_register("get_application")
async def _get_application(session: AsyncSession, application_id: int, args: dict) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    return {
        "stage": app.stage.value if app.stage else None,
        "score": app.score,
        "validated_at": _iso(app.validated_at),
        "invited_at": _iso(app.invited_at),
        "rejected_at": _iso(app.rejected_at),
        "notes": app.notes,
    }


@_register("get_score_breakdown")
async def _get_score_breakdown(session: AsyncSession, application_id: int, args: dict) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    return {
        "score": app.score,
        "rationale": app.score_rationale,
        "breakdown": app.score_breakdown or [],
    }


@_register("get_job")
async def _get_job(session: AsyncSession, application_id: int, args: dict) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    job = await session.get(Job, app.job_id)
    if job is None:
        return {"error": "job not found"}
    return {
        "title": job.title,
        "description": job.description,
        "criteria": job.criteria or [],
        "status": job.status.value if job.status else None,
    }


@_register("list_other_applications_for_candidate")
async def _list_other(session: AsyncSession, application_id: int, args: dict) -> list[dict]:
    app = await session.get(Application, application_id)
    if app is None:
        return []
    rows = (await session.execute(
        select(Application, Job.title)
        .join(Job, Job.id == Application.job_id)
        .where(Application.candidate_id == app.candidate_id)
        .where(Application.id != application_id)
        .order_by(Application.created_at.desc())
    )).all()
    return [
        {
            "application_id": other.id,
            "job_title": job_title,
            "stage": other.stage.value if other.stage else None,
            "score": other.score,
            "created_at": _iso(other.created_at),
        }
        for other, job_title in rows
    ]


# JSON Schema definitions — input_schema=={"type":"object","properties":{}} for no-arg tools.
_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

TOOLS: list[ToolDef] = [
    ToolDef(name="get_candidate",
            description="Read the candidate profile (name, email, skills, experience, education, links).",
            input_schema=_NO_ARGS),
    ToolDef(name="get_application",
            description="Read this application's stage, score, timestamps, and notes.",
            input_schema=_NO_ARGS),
    ToolDef(name="get_score_breakdown",
            description="Read the LLM-generated score and per-criterion rationale.",
            input_schema=_NO_ARGS),
    ToolDef(name="get_job",
            description="Read the job's title, description, and scoring criteria.",
            input_schema=_NO_ARGS),
    ToolDef(name="list_other_applications_for_candidate",
            description="List the same candidate's applications to other jobs (excludes this one).",
            input_schema=_NO_ARGS),
]


def _append_note(app: Application, text: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line = f"[{stamp}] {text}"
    app.notes = (app.notes + "\n\n" + line) if app.notes else line


@_register("save_note")
async def _save_note(session: AsyncSession, application_id: int, args: dict) -> dict:
    text = (args.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    _append_note(app, text)
    await session.commit()
    return {"ok": True, "note_id": application_id}


_VALIDATE_FROM = {Stage.SCORED, Stage.VALIDATED, Stage.REJECTED}
_REJECT_FROM = {Stage.SCORED, Stage.VALIDATED, Stage.REJECTED}


async def _validate_application(
    session: AsyncSession,
    application_id: int,
    args: dict,
    *,
    undo_store: UndoStore | None = None,
) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    if app.stage not in _VALIDATE_FROM:
        return {"error": f"stage {app.stage.value} cannot move to validated"}
    previous = app.stage.value
    app.stage = Stage.VALIDATED
    app.validated_at = datetime.now(timezone.utc)
    notes_arg = (args.get("notes") or "").strip()
    if notes_arg:
        _append_note(app, notes_arg)
    await session.commit()
    store = undo_store or get_default_undo_store()
    token = store.issue(application_id=application_id, previous_stage=previous)
    return {"ok": True, "previous_stage": previous, "undo_token": token}


async def _reject_application(
    session: AsyncSession,
    application_id: int,
    args: dict,
    *,
    undo_store: UndoStore | None = None,
) -> dict:
    reason = (args.get("reason") or "").strip()
    if not reason:
        return {"error": "reason is required"}
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    if app.stage not in _REJECT_FROM:
        return {"error": f"stage {app.stage.value} cannot move to rejected"}
    previous = app.stage.value
    app.stage = Stage.REJECTED
    app.rejected_at = datetime.now(timezone.utc)
    _append_note(app, f"Rejected: {reason}")
    await session.commit()
    store = undo_store or get_default_undo_store()
    token = store.issue(application_id=application_id, previous_stage=previous)
    return {"ok": True, "previous_stage": previous, "undo_token": token}


# validate/reject accept an extra `undo_store` keyword. The variadic
# ToolHandler alias above accepts any kwargs; the agent loop detects these
# two names and threads undo_store explicitly.
_HANDLERS["validate_application"] = _validate_application
_HANDLERS["reject_application"] = _reject_application


# Append the write tools to the registry
TOOLS.extend([
    ToolDef(
        name="save_note",
        description="Append a free-form note (timestamped) to this application's notes field.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "minLength": 1}},
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="validate_application",
        description="Mark this candidate as validated (i.e., approved for the next interview step). Reversible until the recruiter sends an interview invitation.",
        input_schema={
            "type": "object",
            "properties": {"notes": {"type": "string"}},
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="reject_application",
        description="Mark this candidate as rejected. Reversible until the recruiter sends an interview invitation. The reason will be appended to the notes.",
        input_schema={
            "type": "object",
            "properties": {"reason": {"type": "string", "minLength": 1}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    ),
])

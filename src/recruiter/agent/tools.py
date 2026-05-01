from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.types import ToolDef
from recruiter.agent.undo import UndoStore
from recruiter.models import Application, Candidate, Job, Stage


@dataclass
class ToolContext:
    """Per-turn context passed uniformly to every tool handler.

    Carries cross-cutting concerns (DB session, application scope, undo store)
    so handlers share one signature: `async def fn(ctx, args) -> dict | list`.
    Future fields (request_id, principal, dry_run) plug in here without
    growing the agent loop's dispatch.
    """
    session: AsyncSession
    application_id: int
    undo_store: UndoStore


ToolHandler = Callable[[ToolContext, dict], Awaitable[dict | list]]

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
async def _get_candidate(ctx: ToolContext, args: dict) -> dict:
    app = await ctx.session.get(Application, ctx.application_id)
    if app is None:
        return {"error": "application not found"}
    candidate = await ctx.session.get(Candidate, app.candidate_id)
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
async def _get_application(ctx: ToolContext, args: dict) -> dict:
    app = await ctx.session.get(Application, ctx.application_id)
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
async def _get_score_breakdown(ctx: ToolContext, args: dict) -> dict:
    app = await ctx.session.get(Application, ctx.application_id)
    if app is None:
        return {"error": "application not found"}
    return {
        "score": app.score,
        "rationale": app.score_rationale,
        "breakdown": app.score_breakdown or [],
    }


@_register("get_job")
async def _get_job(ctx: ToolContext, args: dict) -> dict:
    app = await ctx.session.get(Application, ctx.application_id)
    if app is None:
        return {"error": "application not found"}
    job = await ctx.session.get(Job, app.job_id)
    if job is None:
        return {"error": "job not found"}
    return {
        "title": job.title,
        "description": job.description,
        "criteria": job.criteria or [],
        "status": job.status.value if job.status else None,
    }


@_register("list_other_applications_for_candidate")
async def _list_other(ctx: ToolContext, args: dict) -> list[dict]:
    app = await ctx.session.get(Application, ctx.application_id)
    if app is None:
        return []
    rows = (await ctx.session.execute(
        select(Application, Job.title)
        .join(Job, Job.id == Application.job_id)
        .where(Application.candidate_id == app.candidate_id)
        .where(Application.id != ctx.application_id)
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
async def _save_note(ctx: ToolContext, args: dict) -> dict:
    text = (args.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}
    app = await ctx.session.get(Application, ctx.application_id)
    if app is None:
        return {"error": "application not found"}
    _append_note(app, text)
    await ctx.session.commit()
    return {"ok": True, "note_id": ctx.application_id}


_VALIDATE_FROM = {Stage.SCORED, Stage.VALIDATED, Stage.REJECTED}
_REJECT_FROM = {Stage.SCORED, Stage.VALIDATED, Stage.REJECTED}


@_register("validate_application")
async def _validate_application(ctx: ToolContext, args: dict) -> dict:
    app = await ctx.session.get(Application, ctx.application_id)
    if app is None:
        return {"error": "application not found"}
    if app.stage not in _VALIDATE_FROM:
        return {"error": f"stage {app.stage.value} cannot move to validated"}
    previous_stage = app.stage.value
    previous_validated_at = app.validated_at.isoformat() if app.validated_at else None
    previous_rejected_at = app.rejected_at.isoformat() if app.rejected_at else None
    app.stage = Stage.VALIDATED
    app.validated_at = datetime.now(timezone.utc)
    notes_arg = (args.get("notes") or "").strip()
    if notes_arg:
        _append_note(app, notes_arg)
    await ctx.session.commit()
    token = ctx.undo_store.issue(
        application_id=ctx.application_id,
        payload={
            "previous_stage": previous_stage,
            "previous_validated_at": previous_validated_at,
            "previous_rejected_at": previous_rejected_at,
        },
    )
    return {"ok": True, "previous_stage": previous_stage, "undo_token": token}


@_register("reject_application")
async def _reject_application(ctx: ToolContext, args: dict) -> dict:
    reason = (args.get("reason") or "").strip()
    if not reason:
        return {"error": "reason is required"}
    app = await ctx.session.get(Application, ctx.application_id)
    if app is None:
        return {"error": "application not found"}
    if app.stage not in _REJECT_FROM:
        return {"error": f"stage {app.stage.value} cannot move to rejected"}
    previous_stage = app.stage.value
    previous_validated_at = app.validated_at.isoformat() if app.validated_at else None
    previous_rejected_at = app.rejected_at.isoformat() if app.rejected_at else None
    app.stage = Stage.REJECTED
    app.rejected_at = datetime.now(timezone.utc)
    _append_note(app, f"Rejected: {reason}")
    await ctx.session.commit()
    token = ctx.undo_store.issue(
        application_id=ctx.application_id,
        payload={
            "previous_stage": previous_stage,
            "previous_validated_at": previous_validated_at,
            "previous_rejected_at": previous_rejected_at,
        },
    )
    return {"ok": True, "previous_stage": previous_stage, "undo_token": token}


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



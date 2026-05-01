from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.types import ToolDef
from recruiter.models import Application, Candidate, Job

ToolHandler = Callable[[AsyncSession, int, dict], Awaitable[dict | list]]

_HANDLERS: dict[str, ToolHandler] = {}


def _register(name: str):
    def deco(fn: ToolHandler) -> ToolHandler:
        _HANDLERS[name] = fn
        return fn
    return deco


def get_tool_handler(name: str) -> ToolHandler:
    if name not in _HANDLERS:
        raise KeyError(f"unknown tool: {name}")
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
    # write tools added in next task
]

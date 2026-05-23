import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.api.deps import get_session, require_user
from recruiter.crypto import settings_cipher
from recruiter.llm.client import LLMClient
from recruiter.models import Job, SettingsRow
from recruiter.pipeline.query_suggester import suggest_search_query
from recruiter.schemas.job import CriteriaItem
from recruiter.schemas.job_suggest import (
    SuggestSearchQueryRequest,
    SuggestSearchQueryResponse,
)
from recruiter.sourcing.linkedin_login import (
    login_and_extract_cookie,
    validate_cookie,
)
from recruiter.sourcing.provider import SearchError, SearchResult
from recruiter.sourcing.search import search_one_source

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/sourcing", tags=["sourcing"], dependencies=[Depends(require_user)])


SourceLiteral = Literal["linkedin", "github", "web"]


class SearchRequest(BaseModel):
    sources: list[SourceLiteral] = Field(min_length=1)
    query: str = Field(min_length=1)
    limit_per_source: int = Field(default=5, ge=1, le=30)


class SearchResultOut(BaseModel):
    name: str
    url: str
    snippet: str
    source: str


class SearchErrorItem(BaseModel):
    source: SourceLiteral
    reason: str
    transient: bool


class SearchResponse(BaseModel):
    results: list[SearchResultOut]
    errors: list[SearchErrorItem]


def _to_out(r: SearchResult) -> SearchResultOut:
    return SearchResultOut(name=r.name, url=r.url, snippet=r.snippet, source=r.source)


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    settings = await session.get(SettingsRow, 1)

    async def run(source: SourceLiteral) -> tuple[SourceLiteral, list[SearchResult] | Exception]:
        try:
            res = await search_one_source(
                source, payload.query, payload.limit_per_source, settings=settings,
            )
            return source, res
        except Exception as exc:
            return source, exc

    outcomes = await asyncio.gather(*[run(s) for s in payload.sources])

    results: list[SearchResultOut] = []
    errors: list[SearchErrorItem] = []
    for source, outcome in outcomes:
        if isinstance(outcome, SearchError):
            errors.append(SearchErrorItem(
                source=source, reason=str(outcome), transient=outcome.transient,
            ))
        elif isinstance(outcome, Exception):
            logger.exception(
                "sourcing.search unexpected error",
                exc_info=outcome,
                extra={"source": source},
            )
            errors.append(SearchErrorItem(
                source=source, reason=f"internal error: {type(outcome).__name__}", transient=True,
            ))
        else:
            results.extend(_to_out(r) for r in outcome)
    return SearchResponse(results=results, errors=errors)


@router.post("/jobs/{job_id}/query/suggest", response_model=SuggestSearchQueryResponse)
async def suggest_query_endpoint(
    job_id: int,
    payload: SuggestSearchQueryRequest,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> SuggestSearchQueryResponse:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    criteria = [CriteriaItem.model_validate(c) for c in (job.criteria or [])]
    try:
        query = await suggest_search_query(
            title=job.title,
            description=job.description or "",
            criteria=criteria,
            sources=payload.sources,
            llm=llm,
        )
    except Exception as exc:
        logger.warning("search-query suggestion failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Query suggestion failed") from exc
    return SuggestSearchQueryResponse(query=query)


# ---------- LinkedIn cookie management ------------------------------------

class LinkedInConnectRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    # Opt-in: when true, the backend persists the email + encrypted
    # password so it can auto-re-login if LinkedIn invalidates the
    # cookie. False (default) keeps today's "cookie only" behaviour.
    remember: bool = False


class LinkedInConnectResponse(BaseModel):
    status: Literal["connected", "challenge", "failed"]
    reason: str | None = None
    set_at: datetime | None = None


class LinkedInStatusResponse(BaseModel):
    connected: bool
    set_at: datetime | None = None
    auto_reconnect_enabled: bool = False


async def _get_or_create_settings(session: AsyncSession) -> SettingsRow:
    row = (await session.execute(select(SettingsRow).limit(1))).scalar_one_or_none()
    if row is None:
        row = SettingsRow(id=1)
        session.add(row)
        await session.flush()
    return row


@router.get("/linkedin/status", response_model=LinkedInStatusResponse)
async def linkedin_status(
    session: AsyncSession = Depends(get_session),
) -> LinkedInStatusResponse:
    row = (await session.execute(select(SettingsRow).limit(1))).scalar_one_or_none()
    if row is None:
        return LinkedInStatusResponse(
            connected=False, set_at=None, auto_reconnect_enabled=False,
        )
    # `auto_reconnect_enabled` is independent of cookie presence — if
    # creds are stored, we'll re-acquire a cookie on the next scrape
    # even if the current one was cleared after a challenge.
    return LinkedInStatusResponse(
        connected=bool(row.linkedin_li_at_enc),
        set_at=row.linkedin_li_at_set_at if row.linkedin_li_at_enc else None,
        auto_reconnect_enabled=bool(
            row.linkedin_email and row.linkedin_password_enc
        ),
    )


@router.post("/linkedin/connect", response_model=LinkedInConnectResponse)
async def linkedin_connect(
    payload: LinkedInConnectRequest,
    session: AsyncSession = Depends(get_session),
) -> LinkedInConnectResponse:
    """Drive Playwright through linkedin.com/login, capture `li_at`,
    persist it encrypted. Password is consumed and dropped — unless
    `remember=True`, in which case email + encrypted password are stored
    for the auto-reconnect path."""
    result = await login_and_extract_cookie(payload.email, payload.password)
    if result.status != "connected" or not result.li_at:
        return LinkedInConnectResponse(status=result.status, reason=result.reason)

    row = await _get_or_create_settings(session)
    row.linkedin_li_at_enc = settings_cipher().encrypt(result.li_at)
    row.linkedin_li_at_set_at = datetime.now(timezone.utc)
    if payload.remember:
        row.linkedin_email = payload.email.strip()
        row.linkedin_password_enc = settings_cipher().encrypt(payload.password)
    else:
        # If the user previously enabled auto-reconnect and is now
        # reconnecting without ticking the box, treat that as an
        # explicit opt-out — drop the stored creds.
        row.linkedin_email = None
        row.linkedin_password_enc = None
    await session.commit()
    return LinkedInConnectResponse(
        status="connected", set_at=row.linkedin_li_at_set_at,
    )


class LinkedInConnectCookieRequest(BaseModel):
    li_at: str = Field(min_length=10, max_length=4096)
    # When true, skip the Playwright /feed round-trip and just store the
    # cookie blind. Faster but the user gets no immediate feedback if
    # the cookie is bad — failures will appear later as needs_paste.
    skip_validation: bool = False


@router.post("/linkedin/connect-cookie", response_model=LinkedInConnectResponse)
async def linkedin_connect_cookie(
    payload: LinkedInConnectCookieRequest,
    session: AsyncSession = Depends(get_session),
) -> LinkedInConnectResponse:
    """Persist a `li_at` cookie the user pasted directly.

    Validates the cookie by hitting linkedin.com once (unless
    `skip_validation=True`). On success, stores the cookie encrypted.
    On rejection, surfaces the reason without persisting anything.

    No password / email is ever involved in this path — auto-reconnect
    is therefore disabled until the user reconnects via the credentials
    flow.
    """
    li_at = payload.li_at.strip()
    if not payload.skip_validation:
        result = await validate_cookie(li_at)
        if result.status != "connected":
            return LinkedInConnectResponse(
                status=result.status, reason=result.reason,
            )

    row = await _get_or_create_settings(session)
    row.linkedin_li_at_enc = settings_cipher().encrypt(li_at)
    row.linkedin_li_at_set_at = datetime.now(timezone.utc)
    # Pasting a cookie is an explicit "I am switching to manual cookie
    # management" — drop any stored creds so auto-reconnect doesn't
    # silently take over with a different identity.
    row.linkedin_email = None
    row.linkedin_password_enc = None
    await session.commit()
    return LinkedInConnectResponse(
        status="connected", set_at=row.linkedin_li_at_set_at,
    )


@router.post("/linkedin/disconnect", status_code=204)
async def linkedin_disconnect(session: AsyncSession = Depends(get_session)) -> None:
    row = (await session.execute(select(SettingsRow).limit(1))).scalar_one_or_none()
    if row is not None:
        row.linkedin_li_at_enc = None
        row.linkedin_li_at_set_at = None
        # Disconnect is a security action — clear stored creds too so
        # nothing lingers if the user hits this thinking it's a logout.
        row.linkedin_email = None
        row.linkedin_password_enc = None
        await session.commit()

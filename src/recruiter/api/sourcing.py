import asyncio
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_user
from recruiter.models import SettingsRow
from recruiter.sourcing.provider import SearchError, SearchResult
from recruiter.sourcing.search import search_one_source


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
    source: str
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
            errors.append(SearchErrorItem(
                source=source, reason=f"internal error: {type(outcome).__name__}", transient=True,
            ))
        else:
            results.extend(_to_out(r) for r in outcome)
    return SearchResponse(results=results, errors=errors)

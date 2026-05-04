from typing import Literal

from recruiter.crypto import settings_cipher
from recruiter.models import SettingsRow
from recruiter.sourcing import provider as sourcing_provider
from recruiter.sourcing.github import GitHubSearchClient
from recruiter.sourcing.provider import SearchError, SearchResult


async def search_one_source(
    source: Literal["linkedin", "github", "web"],
    query: str,
    limit: int,
    *,
    settings: SettingsRow | None,
) -> list[SearchResult]:
    """Run a single search against the chosen source.

    Single source of truth shared by the chat tools (agent/tools.py) and
    the multi-source HTTP endpoint (api/sourcing.py). Callers handle
    LLM-context summary, frontend events, and error mapping; this just
    returns the raw cards or raises SearchError.

    LinkedIn: prepends `site:linkedin.com/in/` to the query and dispatches
    to the configured provider.
    Web: passes the query verbatim to the provider.
    GitHub: uses GitHubSearchClient directly (provider registry is
    LinkedIn/Web-only).

    Always overrides `SearchResult.source` to match the requested source.
    """
    if settings is None:
        raise SearchError(
            "Search isn't configured. Set a provider in Settings → Sourcing.",
            transient=False,
        )

    if source == "github":
        token = None
        if settings.github_token_enc:
            token = settings_cipher().decrypt(settings.github_token_enc)
        client = GitHubSearchClient(token=token)
        try:
            results = await client.search_users(query, limit)
        finally:
            await client.aclose()
        for r in results:
            r.source = "github"
        return results

    # linkedin / web go through the provider registry
    provider = sourcing_provider.resolve(settings)
    if provider is None:
        raise SearchError(
            "Search isn't configured. Set a provider in Settings → Sourcing.",
            transient=False,
        )

    if source == "linkedin":
        full_query = f"site:linkedin.com/in/ {query}"
    else:  # web
        full_query = query

    results = await provider.search(full_query, limit)
    for r in results:
        r.source = source
    return results

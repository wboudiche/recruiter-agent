import re

import httpx

from recruiter.pipeline.parsers.text import ParsedContent

_GITHUB_PROFILE_RE = re.compile(r"^https?://github\.com/([A-Za-z0-9-]+)/?$")
_API_BASE = "https://api.github.com"


async def fetch_github(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | httpx.MockTransport | None = None,
    token: str | None = None,
) -> ParsedContent:
    match = _GITHUB_PROFILE_RE.match(url.strip())
    if not match:
        raise ValueError("not a github profile URL")
    login = match.group(1)

    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(transport=transport, base_url=_API_BASE, headers=headers, timeout=30) as client:
        user_resp = await client.get(f"/users/{login}")
        user_resp.raise_for_status()
        user = user_resp.json()

        repos_resp = await client.get(f"/users/{login}/repos", params={"per_page": 50, "sort": "updated"})
        repos_resp.raise_for_status()
        repos = [r for r in repos_resp.json() if not r.get("fork")]

    lines: list[str] = []
    if user.get("name"):
        lines.append(f"Name: {user['name']}")
    if user.get("login"):
        lines.append(f"GitHub login: {user['login']}")
    if user.get("bio"):
        lines.append(f"Bio: {user['bio']}")
    if user.get("location"):
        lines.append(f"Location: {user['location']}")
    if user.get("email"):
        lines.append(f"Email: {user['email']}")
    if user.get("company"):
        lines.append(f"Company: {user['company']}")
    if user.get("blog"):
        lines.append(f"Website: {user['blog']}")

    if repos:
        lines.append("")
        lines.append("Public repositories (non-forks):")
        for r in repos[:25]:
            lang = r.get("language") or "?"
            stars = r.get("stargazers_count", 0)
            desc = r.get("description") or ""
            lines.append(f"- {r['name']} [{lang}, {stars}★] - {desc}")

    return ParsedContent(
        text="\n".join(lines),
        metadata={"login": login, "source_url": url, "repo_count": len(repos)},
    )

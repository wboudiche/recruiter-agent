import pytest
from httpx import AsyncClient

# Each (method, path_with_placeholders) pair should require auth.
# Path placeholders use a fake int that may 404 if no row — that's fine,
# we're asserting NO route returns 200/202 unauthenticated.
GATED = [
    ("GET",   "/api/jobs"),
    ("POST",  "/api/jobs"),
    ("GET",   "/api/jobs/1"),
    ("GET",   "/api/jobs/1/applications"),
    ("POST",  "/api/jobs/1/candidates"),
    ("POST",  "/api/jobs/1/candidates/upload"),
    ("GET",   "/api/applications/1"),
    ("PATCH", "/api/applications/1"),
    ("POST",  "/api/applications/1/retry"),
    ("POST",  "/api/applications/1/paste"),
    ("POST",  "/api/applications/1/draft-email"),
    ("POST",  "/api/applications/1/notify"),
    ("GET",   "/api/applications/1/chat"),
    ("POST",  "/api/applications/1/chat"),
    ("POST",  "/api/applications/1/undo"),
    ("GET",   "/api/candidates/1"),
    ("GET",   "/api/settings"),
    ("PUT",   "/api/settings"),
    ("GET",   "/api/events"),
    ("POST",  "/api/sourcing/search"),
]


@pytest.mark.parametrize("method,path", GATED)
@pytest.mark.asyncio
async def test_gated_endpoint_requires_auth(
    api_client_unauth: AsyncClient, method: str, path: str,
) -> None:
    r = await api_client_unauth.request(method, path, json={} if method != "GET" else None)
    assert r.status_code == 401, (
        f"{method} {path} returned {r.status_code} unauthenticated; "
        f"add Depends(require_user) to the router."
    )

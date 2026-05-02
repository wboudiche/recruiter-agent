from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from recruiter.config import get_config

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject mutating requests whose Origin header is set but not in the
    allowlist. SameSite=Strict already blocks cross-site cookies on these
    methods; this is belt-and-suspenders for legacy browsers and the
    same-site-but-different-port case.

    Requests without an Origin header (curl, server-to-server) pass
    through — the cookie still has to be valid.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in _MUTATING_METHODS:
            origin = request.headers.get("origin")
            if origin:
                allowed = [o.strip() for o in get_config().allowed_origins.split(",") if o.strip()]
                if origin not in allowed:
                    return JSONResponse(
                        {"detail": f"origin {origin} not allowed"},
                        status_code=403,
                    )
        return await call_next(request)

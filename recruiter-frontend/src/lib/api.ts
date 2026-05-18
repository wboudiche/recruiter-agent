const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public body?: unknown,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

interface ApiOptions extends RequestInit {
  json?: unknown;
  /** When true, a 401 throws an ApiError instead of bouncing to /login.
   * Used by the login form itself, which needs to render the 401 inline. */
  noAuthRedirect?: boolean;
}

export async function api<T = unknown>(
  path: string,
  opts: ApiOptions = {},
): Promise<T> {
  const headers = new Headers(opts.headers);
  if (opts.json !== undefined) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...opts,
    headers,
    body: opts.json !== undefined ? JSON.stringify(opts.json) : opts.body,
    credentials: "include",
  });

  if (response.status === 401 && !opts.noAuthRedirect) {
    const next = encodeURIComponent(
      window.location.pathname + window.location.search,
    );
    // In-app /login decides between password form and SSO based on
    // /api/auth/methods; we no longer hard-redirect to the OIDC start.
    window.location.href = `/login?next=${next}`;
    throw new ApiError(401, "redirecting to login");
  }

  const text = await response.text();
  const body = text ? safeParseJson(text) : undefined;

  if (!response.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : response.statusText;
    throw new ApiError(response.status, detail, body);
  }

  return body as T;
}

function safeParseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

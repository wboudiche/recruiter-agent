# syntax=docker/dockerfile:1.7

# ---- Stage 1: builder ----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
RUN uv sync --frozen --no-dev

# ---- Stage 2: runtime ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
RUN chmod +x /usr/local/bin/backend-entrypoint.sh

# Playwright browser cache: shared system path readable by the app user.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# --only-shell: every launch in this codebase is
# `chromium.launch(headless=True)` with no channel (sourcing/linkedin_login.py,
# pipeline/fetchers/linkedin_playwright.py), which Playwright >=1.49 serves
# from chromium-headless-shell. The full browser was 369MB of image that
# nothing ever executed, and downloading it was ~25 minutes of the build.
#
# Retried: this is the one step that reaches the public internet, and a single
# transient DNS failure killed the whole layer —
#   Error: getaddrinfo EAI_AGAIN cdn.playwright.dev
# — after the download had already been running successfully for 25 minutes,
# with BuildKit then discarding all of it. Three attempts make a blip cost
# seconds instead of a rebuild.
RUN set -eu; \
    for attempt in 1 2 3; do \
        if /app/.venv/bin/python -m playwright install --with-deps --only-shell chromium; then \
            chmod -R o+rx /ms-playwright; \
            exit 0; \
        fi; \
        echo "playwright install failed (attempt ${attempt}/3); retrying in 15s"; \
        sleep 15; \
    done; \
    echo "playwright install failed after 3 attempts"; \
    exit 1

RUN mkdir -p /app/var/resumes && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/backend-entrypoint.sh"]
CMD ["uvicorn", "recruiter.main:app", "--host", "0.0.0.0", "--port", "8000"]

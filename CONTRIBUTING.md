# Contributing

Thanks for your interest. This is a small project — issues, PRs, and
discussion are all welcome.

## Getting set up

```bash
git clone https://github.com/wboudiche/recruiter-agent
cd recruiter-agent
cp .env.example .env   # then fill in the required vars (see README)
docker compose up -d --build
```

UI at http://localhost:8088. Admin credentials are whatever you set in `.env`.

## Running the test suite

```bash
# Backend (pytest)
uv sync
uv run pytest

# Frontend component tests (vitest)
cd recruiter-frontend
npm install
npm test

# Frontend e2e (Playwright) — needs the docker stack running
npm run e2e
# or
npm run e2e:ui   # interactive runner
```

The Playwright suite is self-discovering — it picks any job/application
that exists rather than hard-coding IDs. Run `docker compose up -d`
first.

## Commit style

We use **prefixed commit subjects** to keep `git log` scannable:

| Prefix | When to use |
|---|---|
| `feat(area):` | New user-facing capability |
| `fix(area):` | Bug fix |
| `ui(area):` | UI-only change with no logic shift |
| `sec(area):` | Security hardening (env, CSRF, auth, secrets) |
| `test(area):` | Adding or fixing tests, no behaviour change |
| `docs(area):` | Documentation only |
| `refactor(area):` | Internal restructure, no behaviour change |
| `chore(area):` | Tooling, dependency bumps |

`area` is something like `auth`, `kanban`, `pipeline`, `compose`, `linkedin`.

## Code style

- **Backend**: Python 3.12, async-first, SQLAlchemy 2.x, Pydantic v2,
  `uv` for deps. Avoid bare `except:` and avoid swallowing
  exceptions silently.
- **Frontend**: React 18, TanStack Query, Tailwind, shadcn/ui.
  Run `npx tsc --noEmit` before opening a PR — there are no
  no-lint-rules but type errors block CI.
- **Migrations**: dated prefix (`YYYYMMDD_<slug>.py`). Always test the
  `downgrade` path before merging.

## PR expectations

- Keep PRs focused — one feature or one fix per PR.
- Include screenshots for UI changes.
- If you add a new env var or Settings field, update the README's
  Configuration reference in the same PR.
- E2E tests for any new top-of-funnel flow (add candidate, edit
  candidate, notify wizard, settings) are appreciated but not
  strictly required.

## Security

If you find a security issue, please **don't open a public issue**.
Email the maintainer directly (commit author email in `git log`).

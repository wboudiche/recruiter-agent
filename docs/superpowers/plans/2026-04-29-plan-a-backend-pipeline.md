# Plan A — Backend Pipeline + API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backend that ingests candidate URLs/resumes, extracts structured candidate data via LLM, scores against a job's JD + criteria, and exposes results through REST + SSE. End-state: `curl` adds a candidate to a job and returns a score.

**Architecture:** FastAPI (async) + PostgreSQL (SQLAlchemy 2.0 async, Alembic migrations) + pluggable LLM client (Anthropic + OpenAI-compatible). Pipeline is a deterministic router → fetcher/parser → extractor → scorer chain run in `BackgroundTasks`. SSE pushes stage transitions to clients.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async, asyncpg), Alembic, Pydantic v2, anthropic SDK, httpx, PyMuPDF, python-docx, trafilatura, cryptography (AES-GCM), pytest + pytest-asyncio + pytest-recording, testcontainers-python (Postgres for tests).

**Out of scope (covered in later plans):** Frontend (Plan B), Notifications (Plan C), Chat panel (Plan D).

**Spec reference:** `docs/superpowers/specs/2026-04-29-recruiter-agent-design.md`

---

## File Structure

```
recruiter-agent/
├── pyproject.toml
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── alembic/
│   ├── env.py
│   └── versions/
├── src/recruiter/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entrypoint
│   ├── config.py               # env-driven settings
│   ├── db.py                   # async engine, session
│   ├── crypto.py               # AES-GCM for secrets
│   ├── events.py               # in-process pub/sub for SSE
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── job.py
│   │   ├── candidate.py
│   │   ├── application.py
│   │   ├── notification.py
│   │   ├── settings.py
│   │   └── event_log.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── job.py
│   │   ├── candidate.py
│   │   ├── application.py
│   │   ├── settings.py
│   │   └── extraction.py       # LLM output schemas
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py           # Protocol + FakeLLMClient
│   │   ├── anthropic.py
│   │   └── openai_compat.py
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── orchestrator.py
│   │   ├── extractor.py
│   │   ├── scorer.py
│   │   ├── fetchers/
│   │   │   ├── __init__.py
│   │   │   ├── github.py
│   │   │   ├── webpage.py
│   │   │   └── linkedin_stub.py
│   │   └── parsers/
│   │       ├── __init__.py
│   │       ├── pdf.py
│   │       ├── docx.py
│   │       └── text.py
│   └── api/
│       ├── __init__.py
│       ├── deps.py
│       ├── jobs.py
│       ├── candidates.py
│       ├── applications.py
│       ├── settings.py
│       └── events.py           # SSE endpoint
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   └── resumes/
    ├── unit/
    └── api/
```

Each module has a single responsibility. Models and schemas are split per entity to keep files small. Pipeline subpackages keep fetchers and parsers isolated for independent testing.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Create: `src/recruiter/__init__.py`
- Create: `src/recruiter/main.py`
- Create: `src/recruiter/config.py`
- Create: `tests/conftest.py`
- Create: `tests/test_health.py`
- Create: `.gitignore`

- [ ] **Step 1: Write the failing test**

Create `tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from recruiter.main import app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter'` (or similar).

- [ ] **Step 3: Write `pyproject.toml`**

Create `pyproject.toml`:

```toml
[project]
name = "recruiter-agent"
version = "0.1.0"
description = "Recruiter assistant — Phase 1 backend"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "sqlalchemy[asyncio]>=2.0",
  "asyncpg>=0.29",
  "alembic>=1.13",
  "anthropic>=0.34",
  "httpx>=0.27",
  "PyMuPDF>=1.24",
  "python-docx>=1.1",
  "trafilatura>=1.10",
  "cryptography>=42",
  "python-multipart>=0.0.9",
  "sse-starlette>=2.1",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "pytest-recording>=0.13",
  "testcontainers[postgres]>=4.4",
  "ruff>=0.4",
  "mypy>=1.10",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"
addopts = "-ra"

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]
```

- [ ] **Step 4: Write minimal app and config**

Create `src/recruiter/__init__.py` (empty file).

Create `src/recruiter/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECRUITER_", extra="ignore")

    database_url: str = "postgresql+asyncpg://recruiter:recruiter@localhost:5432/recruiter"
    settings_key: str = "dev-only-32-byte-key-replace-me!"  # 32 bytes
    resume_storage_path: str = "./var/resumes"
    log_level: str = "INFO"


def get_config() -> Config:
    return Config()
```

Create `src/recruiter/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="Recruiter Agent")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Create `.env.example`:

```
RECRUITER_DATABASE_URL=postgresql+asyncpg://recruiter:recruiter@localhost:5432/recruiter
RECRUITER_SETTINGS_KEY=dev-only-32-byte-key-replace-me!
RECRUITER_RESUME_STORAGE_PATH=./var/resumes
RECRUITER_LOG_LEVEL=INFO
```

(The Anthropic API key is stored encrypted in the `Settings` row via the `/api/settings` endpoint — it is not loaded from environment variables.)

Create `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: recruiter
      POSTGRES_PASSWORD: recruiter
      POSTGRES_DB: recruiter
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

Create `.gitignore`:

```
__pycache__/
*.pyc
.venv/
.env
var/
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/
dist/
build/
```

Create `tests/conftest.py` (empty file for now):

```python
```

- [ ] **Step 5: Install deps and run tests**

Run:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/test_health.py -v
```

Expected: PASS — `test_health_endpoint_returns_ok PASSED`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example docker-compose.yml .gitignore src/recruiter tests/
git commit -m "chore: scaffold FastAPI project with health endpoint"
```

---

## Task 2: DB Connection + Alembic

**Files:**
- Create: `src/recruiter/db.py`
- Create: `src/recruiter/models/__init__.py`
- Create: `src/recruiter/models/base.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `tests/conftest.py` (overwrite)
- Create: `tests/unit/test_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_db.py`:

```python
import pytest
from sqlalchemy import text

from recruiter.db import get_engine


@pytest.mark.asyncio
async def test_engine_connects_and_runs_select_one(pg_dsn: str) -> None:
    engine = get_engine(pg_dsn)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await engine.dispose()
```

- [ ] **Step 2: Set up test fixture for Postgres**

Overwrite `tests/conftest.py`:

```python
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_dsn(postgres_container: PostgresContainer) -> str:
    raw = postgres_container.get_connection_url()
    return raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture
async def db_session(pg_dsn: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(pg_dsn)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruiter.db'`.

- [ ] **Step 4: Implement db module**

Create `src/recruiter/db.py`:

```python
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@lru_cache(maxsize=8)
def get_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_dependency(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = get_engine(database_url)
    SessionLocal = get_session_factory(engine)
    async with SessionLocal() as session:
        yield session
```

Create `src/recruiter/models/__init__.py`:

```python
from recruiter.models.base import Base

__all__ = ["Base"]
```

Create `src/recruiter/models/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_db.py -v`
Expected: PASS.

- [ ] **Step 6: Initialize Alembic**

Create `alembic.ini`:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://recruiter:recruiter@localhost:5432/recruiter
prepend_sys_path = src
file_template = %%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d%%(second).2d_%%(slug)s

[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

Create `alembic/script.py.mako`:

```python
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Create `alembic/env.py`:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from recruiter.config import get_config
from recruiter.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_config().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Create empty `alembic/versions/.gitkeep`.

- [ ] **Step 7: Verify Alembic works**

Run:
```bash
docker compose up -d postgres
alembic current
```

Expected: outputs nothing (no migrations yet) and exits 0.

- [ ] **Step 8: Commit**

```bash
git add src/recruiter/db.py src/recruiter/models alembic.ini alembic tests/conftest.py tests/unit
git commit -m "feat(db): add async SQLAlchemy engine and Alembic config"
```

---

## Task 3: Crypto Module for Settings Secrets

**Files:**
- Create: `src/recruiter/crypto.py`
- Create: `tests/unit/test_crypto.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_crypto.py`:

```python
import pytest

from recruiter.crypto import SecretCipher


def test_roundtrip_encrypts_and_decrypts() -> None:
    cipher = SecretCipher(b"0123456789abcdef0123456789abcdef")
    token = cipher.encrypt("my-api-key")
    assert token != "my-api-key"
    assert cipher.decrypt(token) == "my-api-key"


def test_decrypt_rejects_tampered_token() -> None:
    cipher = SecretCipher(b"0123456789abcdef0123456789abcdef")
    token = cipher.encrypt("my-api-key")
    tampered = token[:-2] + "00"
    with pytest.raises(ValueError, match="invalid token"):
        cipher.decrypt(tampered)


def test_key_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SecretCipher(b"too-short")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_crypto.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement crypto module**

Create `src/recruiter/crypto.py`:

```python
import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("key must be 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)
        ct = self._aead.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
        return base64.urlsafe_b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(token.encode("ascii"))
        except Exception as exc:
            raise ValueError("invalid token: not base64") from exc
        if len(raw) < 13:
            raise ValueError("invalid token: too short")
        nonce, ct = raw[:12], raw[12:]
        try:
            return self._aead.decrypt(nonce, ct, associated_data=None).decode("utf-8")
        except InvalidTag as exc:
            raise ValueError("invalid token: bad tag") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_crypto.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/crypto.py tests/unit/test_crypto.py
git commit -m "feat(crypto): add AES-GCM SecretCipher for settings secrets"
```

---

## Task 4: Models — Job, Candidate, Application + First Migration

**Files:**
- Create: `src/recruiter/models/job.py`
- Create: `src/recruiter/models/candidate.py`
- Create: `src/recruiter/models/application.py`
- Modify: `src/recruiter/models/__init__.py`
- Create: `tests/unit/test_models_core.py`
- Create: `alembic/versions/<auto>_initial_core.py` (auto-generated)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_models_core.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, Job, Stage


@pytest.mark.asyncio
async def test_create_job_and_application_roundtrip(db_session_with_schema: AsyncSession) -> None:
    job = Job(title="Backend Engineer", description="Build APIs", criteria=[])
    candidate = Candidate(full_name="Alice", email="alice@example.com")
    db_session_with_schema.add_all([job, candidate])
    await db_session_with_schema.flush()

    app_row = Application(
        job_id=job.id,
        candidate_id=candidate.id,
        stage=Stage.EXTRACTING,
    )
    db_session_with_schema.add(app_row)
    await db_session_with_schema.commit()

    fetched = await db_session_with_schema.get(Application, app_row.id)
    assert fetched is not None
    assert fetched.stage == Stage.EXTRACTING
    assert fetched.job_id == job.id
```

Add this fixture to `tests/conftest.py` (append, do not overwrite the existing fixtures):

```python
from sqlalchemy.ext.asyncio import create_async_engine

from recruiter.models import Base


@pytest.fixture
async def db_session_with_schema(pg_dsn: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(pg_dsn)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_models_core.py -v`
Expected: FAIL — `ImportError: cannot import name 'Job'` etc.

- [ ] **Step 3: Implement Job model**

Create `src/recruiter/models/job.py`:

```python
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class JobStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String)
    criteria: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status"), default=JobStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Implement Candidate model**

Create `src/recruiter/models/candidate.py`:

```python
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class SourceType(str, Enum):
    URL = "url"
    RESUME = "resume"
    PASTE = "paste"


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(255))
    headline: Mapped[str | None] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(String)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    experience: Mapped[list[dict]] = mapped_column(JSON, default=list)
    education: Mapped[list[dict]] = mapped_column(JSON, default=list)
    links: Mapped[list[dict]] = mapped_column(JSON, default=list)
    source_type: Mapped[SourceType | None] = mapped_column(SAEnum(SourceType, name="source_type"))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    resume_path: Mapped[str | None] = mapped_column(String(1024))
    raw_extracted: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 5: Implement Application model**

Create `src/recruiter/models/application.py`:

```python
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class Stage(str, Enum):
    SOURCED = "sourced"      # reserved for Phase 2 bulk; unused in Phase 1
    EXTRACTING = "extracting"
    SCORED = "scored"
    VALIDATED = "validated"
    INVITED = "invited"
    SCHEDULED = "scheduled"
    REJECTED = "rejected"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    stage: Mapped[Stage] = mapped_column(SAEnum(Stage, name="stage"))
    score: Mapped[int | None] = mapped_column(Integer)
    score_breakdown: Mapped[list[dict] | None] = mapped_column(JSON)
    score_rationale: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 6: Update `models/__init__.py`**

Overwrite `src/recruiter/models/__init__.py`:

```python
from recruiter.models.application import Application, Stage
from recruiter.models.base import Base
from recruiter.models.candidate import Candidate, SourceType
from recruiter.models.job import Job, JobStatus

__all__ = [
    "Application",
    "Base",
    "Candidate",
    "Job",
    "JobStatus",
    "SourceType",
    "Stage",
]
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_models_core.py -v`
Expected: PASS.

- [ ] **Step 8: Generate the first Alembic migration**

Run:
```bash
docker compose up -d postgres
alembic revision --autogenerate -m "initial core models"
```

Inspect the generated file in `alembic/versions/` — confirm it creates `jobs`, `candidates`, `applications` tables and the relevant enums.

- [ ] **Step 9: Apply and verify migration**

Run:
```bash
alembic upgrade head
alembic current
```

Expected: `alembic current` shows the new revision id.

- [ ] **Step 10: Commit**

```bash
git add src/recruiter/models tests/unit/test_models_core.py tests/conftest.py alembic/versions
git commit -m "feat(models): add Job, Candidate, Application + initial migration"
```

---

## Task 5: Models — Notification, Settings, EventLog + Migration

**Files:**
- Create: `src/recruiter/models/notification.py`
- Create: `src/recruiter/models/settings.py`
- Create: `src/recruiter/models/event_log.py`
- Modify: `src/recruiter/models/__init__.py`
- Create: `tests/unit/test_models_aux.py`
- Create: `alembic/versions/<auto>_aux_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_models_aux.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import (
    EventLog,
    Notification,
    NotificationChannel,
    NotificationProvider,
    NotificationStatus,
    SettingsRow,
)


@pytest.mark.asyncio
async def test_create_notification_and_settings_roundtrip(db_session_with_schema: AsyncSession) -> None:
    settings = SettingsRow(
        id=1,
        default_llm_provider="anthropic",
        recruiter_email="me@example.com",
    )
    db_session_with_schema.add(settings)
    await db_session_with_schema.commit()

    n = Notification(
        application_id=None,
        channel=NotificationChannel.EMAIL,
        provider=NotificationProvider.SMTP,
        subject="hi",
        body="body",
        status=NotificationStatus.DRAFT,
    )
    db_session_with_schema.add(n)
    await db_session_with_schema.commit()
    assert n.id is not None


@pytest.mark.asyncio
async def test_event_log_can_be_inserted(db_session_with_schema: AsyncSession) -> None:
    e = EventLog(event_type="application.scored", payload={"score": 87})
    db_session_with_schema.add(e)
    await db_session_with_schema.commit()
    assert e.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_models_aux.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement Notification model**

Create `src/recruiter/models/notification.py`:

```python
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class NotificationChannel(str, Enum):
    EMAIL = "email"
    CALENDAR = "calendar"


class NotificationProvider(str, Enum):
    GMAIL = "gmail"
    SMTP = "smtp"


class NotificationStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    FAILED = "failed"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notification_channel", values_callable=lambda x: [e.value for e in x])
    )
    provider: Mapped[NotificationProvider] = mapped_column(
        SAEnum(NotificationProvider, name="notification_provider", values_callable=lambda x: [e.value for e in x])
    )
    subject: Mapped[str | None] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(String)
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status", values_callable=lambda x: [e.value for e in x])
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(String)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Implement Settings model**

Create `src/recruiter/models/settings.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class SettingsRow(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_llm_provider: Mapped[str] = mapped_column(String(32), default="anthropic")
    anthropic_api_key_enc: Mapped[str | None] = mapped_column(String)
    local_llm_url: Mapped[str | None] = mapped_column(String(2048))
    model_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    google_oauth_tokens_enc: Mapped[str | None] = mapped_column(String)
    smtp_config_enc: Mapped[str | None] = mapped_column(String)
    recruiter_name: Mapped[str | None] = mapped_column(String(255))
    recruiter_email: Mapped[str | None] = mapped_column(String(255))
    monthly_llm_spend_cap_usd: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 5: Implement EventLog model**

Create `src/recruiter/models/event_log.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(128))
    actor: Mapped[str] = mapped_column(String(64), default="recruiter")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 6: Update `models/__init__.py`**

Overwrite `src/recruiter/models/__init__.py`:

```python
from recruiter.models.application import Application, Stage
from recruiter.models.base import Base
from recruiter.models.candidate import Candidate, SourceType
from recruiter.models.event_log import EventLog
from recruiter.models.job import Job, JobStatus
from recruiter.models.notification import (
    Notification,
    NotificationChannel,
    NotificationProvider,
    NotificationStatus,
)
from recruiter.models.settings import SettingsRow

__all__ = [
    "Application",
    "Base",
    "Candidate",
    "EventLog",
    "Job",
    "JobStatus",
    "Notification",
    "NotificationChannel",
    "NotificationProvider",
    "NotificationStatus",
    "SettingsRow",
    "SourceType",
    "Stage",
]
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_models_aux.py -v`
Expected: 2 PASSED.

- [ ] **Step 8: Generate migration**

```bash
alembic revision --autogenerate -m "auxiliary models"
alembic upgrade head
```

Inspect the generated migration to confirm `notifications`, `settings`, `event_logs` are created.

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/models tests/unit/test_models_aux.py alembic/versions
git commit -m "feat(models): add Notification, Settings, EventLog + migration"
```

---

## Task 6: Pydantic Schemas

**Files:**
- Create: `src/recruiter/schemas/__init__.py`
- Create: `src/recruiter/schemas/job.py`
- Create: `src/recruiter/schemas/candidate.py`
- Create: `src/recruiter/schemas/application.py`
- Create: `src/recruiter/schemas/settings.py`
- Create: `src/recruiter/schemas/extraction.py`
- Create: `tests/unit/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from recruiter.schemas.extraction import ExtractedCandidate, ScoreResult
from recruiter.schemas.job import CriteriaItem, JobCreate


def test_job_create_requires_title_and_description() -> None:
    j = JobCreate(title="Backend", description="Build APIs", criteria=[])
    assert j.title == "Backend"

    with pytest.raises(ValidationError):
        JobCreate(title="", description="x", criteria=[])


def test_criteria_weight_in_range() -> None:
    CriteriaItem(name="Rust", weight=0.5, description="3+ yrs")
    with pytest.raises(ValidationError):
        CriteriaItem(name="Rust", weight=2.0, description="x")


def test_extracted_candidate_minimal() -> None:
    e = ExtractedCandidate(full_name="Alice", skills=["Python"])
    assert e.full_name == "Alice"


def test_score_result_validates_range() -> None:
    ScoreResult(score=80, breakdown=[], rationale="ok")
    with pytest.raises(ValidationError):
        ScoreResult(score=120, breakdown=[], rationale="x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement schemas**

Create `src/recruiter/schemas/__init__.py` (empty file).

Create `src/recruiter/schemas/job.py`:

```python
from datetime import datetime

from pydantic import BaseModel, Field


class CriteriaItem(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    weight: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=1)


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    criteria: list[CriteriaItem] = Field(default_factory=list)


class JobUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    criteria: list[CriteriaItem] | None = None
    status: str | None = None


class JobRead(BaseModel):
    id: int
    title: str
    description: str
    criteria: list[CriteriaItem]
    status: str
    created_at: datetime
    updated_at: datetime
```

Create `src/recruiter/schemas/candidate.py`:

```python
from datetime import datetime

from pydantic import BaseModel


class ExperienceItem(BaseModel):
    title: str | None = None
    company: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None


class EducationItem(BaseModel):
    school: str | None = None
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None


class LinkItem(BaseModel):
    label: str
    url: str


class CandidateRead(BaseModel):
    id: int
    full_name: str | None
    email: str | None
    phone: str | None
    location: str | None
    headline: str | None
    summary: str | None
    skills: list[str]
    experience: list[ExperienceItem]
    education: list[EducationItem]
    links: list[LinkItem]
    source_type: str | None
    source_url: str | None
    resume_path: str | None
    created_at: datetime
    updated_at: datetime


class CandidateCreateFromUrl(BaseModel):
    url: str


class CandidateCreateFromPaste(BaseModel):
    content: str
    source_url: str | None = None
```

Create `src/recruiter/schemas/application.py`:

```python
from datetime import datetime

from pydantic import BaseModel


class ScoreBreakdownItem(BaseModel):
    criterion: str
    weight: float
    score: int
    rationale: str


class ApplicationRead(BaseModel):
    id: int
    job_id: int
    candidate_id: int
    stage: str
    score: int | None
    score_breakdown: list[ScoreBreakdownItem] | None
    score_rationale: str | None
    notes: str | None
    validated_at: datetime | None
    invited_at: datetime | None
    scheduled_at: datetime | None
    rejected_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

Create `src/recruiter/schemas/settings.py`:

```python
from pydantic import BaseModel


class SettingsRead(BaseModel):
    default_llm_provider: str
    has_anthropic_api_key: bool
    local_llm_url: str | None
    model_overrides: dict
    has_google_oauth_tokens: bool
    has_smtp_config: bool
    recruiter_name: str | None
    recruiter_email: str | None
    monthly_llm_spend_cap_usd: int | None


class SettingsUpdate(BaseModel):
    default_llm_provider: str | None = None
    anthropic_api_key: str | None = None
    local_llm_url: str | None = None
    model_overrides: dict | None = None
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    monthly_llm_spend_cap_usd: int | None = None
```

Create `src/recruiter/schemas/extraction.py`:

```python
from pydantic import BaseModel, Field

from recruiter.schemas.candidate import EducationItem, ExperienceItem, LinkItem


class ExtractedCandidate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    links: list[LinkItem] = Field(default_factory=list)


class ScoreBreakdownItem(BaseModel):
    criterion: str
    weight: float = Field(ge=0.0, le=1.0)
    score: int = Field(ge=0, le=100)
    rationale: str


class ScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    breakdown: list[ScoreBreakdownItem]
    rationale: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/schemas tests/unit/test_schemas.py
git commit -m "feat(schemas): add Pydantic schemas for jobs, candidates, applications, extraction"
```

---

## Task 7: LLM Client Protocol + FakeLLMClient

**Files:**
- Create: `src/recruiter/llm/__init__.py`
- Create: `src/recruiter/llm/client.py`
- Create: `tests/unit/test_llm_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_llm_client.py`:

```python
import pytest

from recruiter.llm.client import FakeLLMClient, LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate


@pytest.mark.asyncio
async def test_fake_chat_returns_canned_response() -> None:
    fake = FakeLLMClient(text_responses=["hello"])
    out = await fake.chat(messages=[LLMMessage(role="user", content="hi")])
    assert out == "hello"


@pytest.mark.asyncio
async def test_fake_structured_returns_typed_response() -> None:
    expected = ExtractedCandidate(full_name="Alice", skills=["Python"])
    fake = FakeLLMClient(structured_responses=[expected])
    out = await fake.chat_structured(
        messages=[LLMMessage(role="user", content="extract")],
        schema=ExtractedCandidate,
    )
    assert out.full_name == "Alice"


@pytest.mark.asyncio
async def test_fake_raises_when_responses_exhausted() -> None:
    fake = FakeLLMClient(text_responses=[])
    with pytest.raises(RuntimeError, match="exhausted"):
        await fake.chat(messages=[LLMMessage(role="user", content="hi")])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_llm_client.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement client protocol + fake**

Create `src/recruiter/llm/__init__.py`:

```python
from recruiter.llm.client import FakeLLMClient, LLMClient, LLMMessage

__all__ = ["FakeLLMClient", "LLMClient", "LLMMessage"]
```

Create `src/recruiter/llm/client.py`:

```python
from collections import deque
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str: ...

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T: ...


class FakeLLMClient:
    def __init__(
        self,
        *,
        text_responses: list[str] | None = None,
        structured_responses: list[BaseModel] | None = None,
    ) -> None:
        self._text = deque(text_responses or [])
        self._structured = deque(structured_responses or [])
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append({"kind": "chat", "messages": messages, "system": system})
        if not self._text:
            raise RuntimeError("FakeLLMClient text_responses exhausted")
        return self._text.popleft()

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T:
        self.calls.append({"kind": "structured", "messages": messages, "system": system, "schema": schema.__name__})
        if not self._structured:
            raise RuntimeError("FakeLLMClient structured_responses exhausted")
        nxt = self._structured.popleft()
        if not isinstance(nxt, schema):
            raise TypeError(f"FakeLLMClient queued response is {type(nxt).__name__}, expected {schema.__name__}")
        return nxt
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_llm_client.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/llm tests/unit/test_llm_client.py
git commit -m "feat(llm): add LLMClient protocol and FakeLLMClient for tests"
```

---

## Task 8: Anthropic LLM Implementation

**Files:**
- Create: `src/recruiter/llm/anthropic.py`
- Create: `tests/unit/test_anthropic_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_anthropic_client.py`:

```python
import pytest

from recruiter.llm.anthropic import AnthropicLLMClient
from recruiter.llm.client import LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate


@pytest.mark.asyncio
async def test_chat_uses_anthropic_messages_create(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeMessage:
        def __init__(self) -> None:
            self.content = [type("B", (), {"text": "hello", "type": "text"})()]

    class FakeMessages:
        async def create(self, **kwargs: object) -> FakeMessage:
            captured.update(kwargs)
            return FakeMessage()

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr("recruiter.llm.anthropic.AsyncAnthropic", FakeAsyncAnthropic)

    client = AnthropicLLMClient(api_key="test", model="claude-sonnet-4-6")
    out = await client.chat(messages=[LLMMessage(role="user", content="hi")], system="be helpful")
    assert out == "hello"
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["system"] == "be helpful"


@pytest.mark.asyncio
async def test_chat_structured_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMessage:
        def __init__(self) -> None:
            self.content = [type("B", (), {"text": '{"full_name":"Alice","skills":["Python"]}', "type": "text"})()]

    class FakeMessages:
        async def create(self, **kwargs: object) -> FakeMessage:
            return FakeMessage()

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr("recruiter.llm.anthropic.AsyncAnthropic", FakeAsyncAnthropic)

    client = AnthropicLLMClient(api_key="test", model="claude-sonnet-4-6")
    result = await client.chat_structured(
        messages=[LLMMessage(role="user", content="extract")],
        schema=ExtractedCandidate,
    )
    assert result.full_name == "Alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_anthropic_client.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement Anthropic client**

Create `src/recruiter/llm/anthropic.py`:

```python
import json
from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from recruiter.llm.client import LLMMessage

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicLLMClient:
    def __init__(self, *, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if system is not None:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)
        parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        return "".join(parts)

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T:
        json_schema = schema.model_json_schema()
        sys_combined = (system or "") + (
            "\n\nRespond ONLY with a single JSON object that matches this schema. "
            "No prose, no markdown fences.\n"
            f"Schema: {json.dumps(json_schema)}"
        )
        text = await self.chat(
            messages=messages,
            system=sys_combined.strip(),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return schema.model_validate_json(_strip_fences(text))


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_anthropic_client.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/llm/anthropic.py tests/unit/test_anthropic_client.py
git commit -m "feat(llm): add Anthropic Claude client implementation"
```

---

## Task 9: OpenAI-Compat LLM Implementation

**Files:**
- Create: `src/recruiter/llm/openai_compat.py`
- Create: `tests/unit/test_openai_compat_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_openai_compat_client.py`:

```python
import json

import httpx
import pytest

from recruiter.llm.client import LLMMessage
from recruiter.llm.openai_compat import OpenAICompatLLMClient
from recruiter.schemas.extraction import ExtractedCandidate


@pytest.mark.asyncio
async def test_chat_calls_chat_completions_endpoint() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        body = {"choices": [{"message": {"content": "hello"}}]}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = OpenAICompatLLMClient(
        base_url="http://localhost:8001/v1",
        model="gpt-oss-120b",
        api_key="not-needed",
        transport=transport,
    )
    out = await client.chat(messages=[LLMMessage(role="user", content="hi")], system="be helpful")
    assert out == "hello"
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["body"]["model"] == "gpt-oss-120b"
    assert captured["body"]["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_chat_structured_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"choices": [{"message": {"content": '{"full_name":"Alice","skills":["Python"]}'}}]}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = OpenAICompatLLMClient(
        base_url="http://localhost:8001/v1",
        model="gpt-oss-120b",
        api_key="x",
        transport=transport,
    )
    result = await client.chat_structured(
        messages=[LLMMessage(role="user", content="extract")],
        schema=ExtractedCandidate,
    )
    assert result.full_name == "Alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_openai_compat_client.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement OpenAI-compat client**

Create `src/recruiter/llm/openai_compat.py`:

```python
import json
from typing import TypeVar

import httpx
from pydantic import BaseModel

from recruiter.llm.client import LLMMessage

T = TypeVar("T", bound=BaseModel)


class OpenAICompatLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | httpx.MockTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        body_messages = []
        if system is not None:
            body_messages.append({"role": "system", "content": system})
        body_messages.extend({"role": m.role, "content": m.content} for m in messages)
        body = {
            "model": self._model,
            "messages": body_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=body,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T:
        json_schema = schema.model_json_schema()
        sys_combined = (system or "") + (
            "\n\nRespond ONLY with a single JSON object that matches this schema. "
            "No prose, no markdown fences.\n"
            f"Schema: {json.dumps(json_schema)}"
        )
        text = await self.chat(
            messages=messages,
            system=sys_combined.strip(),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return schema.model_validate_json(_strip_fences(text))

    async def aclose(self) -> None:
        await self._client.aclose()


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_openai_compat_client.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/llm/openai_compat.py tests/unit/test_openai_compat_client.py
git commit -m "feat(llm): add OpenAI-compatible client for local Ollama/vLLM"
```

---

## Task 10: Pipeline Parser — Plain Text

**Files:**
- Create: `src/recruiter/pipeline/__init__.py`
- Create: `src/recruiter/pipeline/parsers/__init__.py`
- Create: `src/recruiter/pipeline/parsers/text.py`
- Create: `tests/unit/test_text_parser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_text_parser.py`:

```python
from recruiter.pipeline.parsers.text import parse_text


def test_parse_text_preserves_internal_newlines() -> None:
    result = parse_text("Alice\nPython, Rust\n")
    assert result.text == "Alice\nPython, Rust"  # trailing newline stripped, internal preserved
    assert result.metadata == {}


def test_parse_text_strips_outer_whitespace() -> None:
    result = parse_text("   Alice\n  ")
    assert result.text == "Alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_text_parser.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement text parser**

Create `src/recruiter/pipeline/__init__.py` (empty file).

Create `src/recruiter/pipeline/parsers/__init__.py` (empty file).

Create `src/recruiter/pipeline/parsers/text.py`:

```python
from dataclasses import dataclass, field


@dataclass
class ParsedContent:
    text: str
    metadata: dict = field(default_factory=dict)


def parse_text(content: str) -> ParsedContent:
    return ParsedContent(text=content.strip(), metadata={})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_text_parser.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline tests/unit/test_text_parser.py
git commit -m "feat(pipeline): add text parser"
```

---

## Task 11: Pipeline Parser — PDF

**Files:**
- Create: `src/recruiter/pipeline/parsers/pdf.py`
- Create: `tests/fixtures/resumes/sample.pdf` (binary, generated)
- Create: `tests/unit/test_pdf_parser.py`

- [ ] **Step 1: Generate a sample PDF for tests**

Run:
```bash
mkdir -p tests/fixtures/resumes
python -c "
import fitz
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 72), 'Alice Doe\\nSenior Backend Engineer\\nPython, Rust, Postgres')
doc.save('tests/fixtures/resumes/sample.pdf')
"
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_pdf_parser.py`:

```python
from pathlib import Path

from recruiter.pipeline.parsers.pdf import parse_pdf

FIXTURE = Path(__file__).parent.parent / "fixtures/resumes/sample.pdf"


def test_parse_pdf_extracts_text() -> None:
    result = parse_pdf(FIXTURE.read_bytes())
    assert "Alice Doe" in result.text
    assert "Python" in result.text
    assert result.metadata["page_count"] == 1


def test_parse_pdf_raises_on_invalid_bytes() -> None:
    import pytest
    with pytest.raises(ValueError, match="not a valid PDF"):
        parse_pdf(b"not a pdf")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_pdf_parser.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 4: Implement PDF parser**

Create `src/recruiter/pipeline/parsers/pdf.py`:

```python
import fitz  # PyMuPDF

from recruiter.pipeline.parsers.text import ParsedContent


def parse_pdf(data: bytes) -> ParsedContent:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("not a valid PDF") from exc
    try:
        chunks = [page.get_text("text") for page in doc]
        text = "\n".join(chunks).strip()
        return ParsedContent(text=text, metadata={"page_count": doc.page_count})
    finally:
        doc.close()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_pdf_parser.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/pipeline/parsers/pdf.py tests/unit/test_pdf_parser.py tests/fixtures/resumes/sample.pdf
git commit -m "feat(pipeline): add PDF parser using PyMuPDF"
```

---

## Task 12: Pipeline Parser — DOCX

**Files:**
- Create: `src/recruiter/pipeline/parsers/docx.py`
- Create: `tests/fixtures/resumes/sample.docx`
- Create: `tests/unit/test_docx_parser.py`

- [ ] **Step 1: Generate a sample DOCX**

Run:
```bash
python -c "
from docx import Document
d = Document()
d.add_paragraph('Alice Doe')
d.add_paragraph('Senior Backend Engineer')
d.add_paragraph('Python, Rust, Postgres')
d.save('tests/fixtures/resumes/sample.docx')
"
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_docx_parser.py`:

```python
from pathlib import Path

import pytest

from recruiter.pipeline.parsers.docx import parse_docx

FIXTURE = Path(__file__).parent.parent / "fixtures/resumes/sample.docx"


def test_parse_docx_extracts_text() -> None:
    result = parse_docx(FIXTURE.read_bytes())
    assert "Alice Doe" in result.text
    assert "Rust" in result.text


def test_parse_docx_raises_on_invalid_bytes() -> None:
    with pytest.raises(ValueError, match="not a valid DOCX"):
        parse_docx(b"not a docx")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_docx_parser.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 4: Implement DOCX parser**

Create `src/recruiter/pipeline/parsers/docx.py`:

```python
import io
import zipfile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from recruiter.pipeline.parsers.text import ParsedContent


def parse_docx(data: bytes) -> ParsedContent:
    try:
        doc = Document(io.BytesIO(data))
    except (PackageNotFoundError, zipfile.BadZipFile) as exc:
        raise ValueError("not a valid DOCX") from exc
    paragraphs = [p.text for p in doc.paragraphs if p.text]
    return ParsedContent(text="\n".join(paragraphs).strip(), metadata={})
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_docx_parser.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/pipeline/parsers/docx.py tests/unit/test_docx_parser.py tests/fixtures/resumes/sample.docx
git commit -m "feat(pipeline): add DOCX parser using python-docx"
```

---

## Task 13: Pipeline Fetcher — LinkedIn Stub

**Files:**
- Create: `src/recruiter/pipeline/fetchers/__init__.py`
- Create: `src/recruiter/pipeline/fetchers/linkedin_stub.py`
- Create: `tests/unit/test_linkedin_stub.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_linkedin_stub.py`:

```python
from recruiter.pipeline.fetchers.linkedin_stub import fetch_linkedin


def test_fetch_linkedin_returns_empty_text_with_url_metadata() -> None:
    result = fetch_linkedin("https://www.linkedin.com/in/alice/")
    assert result.text == ""
    assert result.metadata["needs_paste"] is True
    assert result.metadata["source_url"] == "https://www.linkedin.com/in/alice/"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_linkedin_stub.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement LinkedIn stub**

Create `src/recruiter/pipeline/fetchers/__init__.py` (empty file).

Create `src/recruiter/pipeline/fetchers/linkedin_stub.py`:

```python
from recruiter.pipeline.parsers.text import ParsedContent


def fetch_linkedin(url: str) -> ParsedContent:
    return ParsedContent(text="", metadata={"needs_paste": True, "source_url": url})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_linkedin_stub.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/fetchers tests/unit/test_linkedin_stub.py
git commit -m "feat(pipeline): add LinkedIn stub fetcher"
```

---

## Task 14: Pipeline Fetcher — GitHub

**Files:**
- Create: `src/recruiter/pipeline/fetchers/github.py`
- Create: `tests/unit/test_github_fetcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_github_fetcher.py`:

```python
import httpx
import pytest

from recruiter.pipeline.fetchers.github import fetch_github


@pytest.mark.asyncio
async def test_fetch_github_combines_user_and_repos() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/alice":
            return httpx.Response(
                200,
                json={
                    "login": "alice",
                    "name": "Alice Doe",
                    "bio": "Backend engineer",
                    "location": "Paris",
                    "blog": "https://alice.dev",
                    "email": "alice@example.com",
                    "company": "Acme",
                },
            )
        if request.url.path == "/users/alice/repos":
            return httpx.Response(
                200,
                json=[
                    {"name": "serverpaint", "description": "Distributed paint", "language": "Rust", "stargazers_count": 12, "fork": False},
                    {"name": "fork-thing", "description": "irrelevant", "language": "Go", "stargazers_count": 0, "fork": True},
                ],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = await fetch_github("https://github.com/alice", transport=transport)

    assert "Alice Doe" in result.text
    assert "Backend engineer" in result.text
    assert "serverpaint" in result.text
    assert "fork-thing" not in result.text  # forks excluded
    assert result.metadata["login"] == "alice"


@pytest.mark.asyncio
async def test_fetch_github_rejects_non_github_urls() -> None:
    with pytest.raises(ValueError, match="not a github profile URL"):
        await fetch_github("https://example.com/foo")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_github_fetcher.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement GitHub fetcher**

Create `src/recruiter/pipeline/fetchers/github.py`:

```python
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
            lines.append(f"- {r['name']} [{lang}, {stars}★] — {desc}")

    return ParsedContent(
        text="\n".join(lines),
        metadata={"login": login, "source_url": url, "repo_count": len(repos)},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_github_fetcher.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/fetchers/github.py tests/unit/test_github_fetcher.py
git commit -m "feat(pipeline): add GitHub fetcher using public API"
```

---

## Task 15: Pipeline Fetcher — Generic Webpage

**Files:**
- Create: `src/recruiter/pipeline/fetchers/webpage.py`
- Create: `tests/unit/test_webpage_fetcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_webpage_fetcher.py`:

```python
import httpx
import pytest

from recruiter.pipeline.fetchers.webpage import fetch_webpage

SAMPLE_HTML = """
<!doctype html>
<html><head><title>Alice's Portfolio</title></head>
<body>
  <header>NAV</header>
  <article>
    <h1>Alice Doe</h1>
    <p>I'm a senior backend engineer working with Rust and Postgres.</p>
  </article>
  <footer>FOOTER</footer>
</body></html>
"""


@pytest.mark.asyncio
async def test_fetch_webpage_extracts_main_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=SAMPLE_HTML)

    transport = httpx.MockTransport(handler)
    result = await fetch_webpage("https://alice.dev", transport=transport)
    assert "Alice Doe" in result.text
    assert "Rust" in result.text
    assert result.metadata["source_url"] == "https://alice.dev"


@pytest.mark.asyncio
async def test_fetch_webpage_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with pytest.raises(ValueError, match="fetch failed"):
        await fetch_webpage("https://nope.example", transport=transport)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_webpage_fetcher.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement webpage fetcher**

Create `src/recruiter/pipeline/fetchers/webpage.py`:

```python
import httpx
import trafilatura

from recruiter.pipeline.parsers.text import ParsedContent


async def fetch_webpage(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | httpx.MockTransport | None = None,
) -> ParsedContent:
    async with httpx.AsyncClient(
        transport=transport,
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "recruiter-agent/0.1"},
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"fetch failed: {exc}") from exc

    html = response.text
    extracted = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    return ParsedContent(text=extracted.strip(), metadata={"source_url": url, "status_code": response.status_code})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_webpage_fetcher.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/fetchers/webpage.py tests/unit/test_webpage_fetcher.py
git commit -m "feat(pipeline): add generic webpage fetcher with trafilatura"
```

---

## Task 16: Pipeline Router

**Files:**
- Create: `src/recruiter/pipeline/router.py`
- Create: `tests/unit/test_router.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_router.py`:

```python
import pytest

from recruiter.pipeline.router import RoutedInput, classify_url


def test_classify_github_url() -> None:
    assert classify_url("https://github.com/alice") == "github"
    assert classify_url("http://github.com/bob/") == "github"


def test_classify_linkedin_url() -> None:
    assert classify_url("https://www.linkedin.com/in/alice/") == "linkedin"
    assert classify_url("https://linkedin.com/in/bob") == "linkedin"


def test_classify_generic_url() -> None:
    assert classify_url("https://alice.dev") == "webpage"
    assert classify_url("https://example.com/about") == "webpage"


def test_classify_invalid_url() -> None:
    with pytest.raises(ValueError, match="invalid URL"):
        classify_url("not a url")


def test_routed_input_holds_kind_and_payload() -> None:
    r = RoutedInput(kind="paste", text="hello", source_url=None, resume_path=None)
    assert r.kind == "paste"
    assert r.text == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_router.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement router**

Create `src/recruiter/pipeline/router.py`:

```python
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

InputKind = Literal["github", "linkedin", "webpage", "paste", "pdf", "docx"]


@dataclass
class RoutedInput:
    kind: InputKind
    text: str | None
    source_url: str | None
    resume_path: str | None


def classify_url(url: str) -> InputKind:
    try:
        parsed = urlparse(url.strip())
    except Exception as exc:
        raise ValueError("invalid URL") from exc
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid URL")
    host = parsed.netloc.lower().lstrip("www.")
    if host == "github.com":
        return "github"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    return "webpage"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_router.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/router.py tests/unit/test_router.py
git commit -m "feat(pipeline): add URL classifier and RoutedInput type"
```

---

## Task 17: Pipeline Extractor

**Files:**
- Create: `src/recruiter/pipeline/extractor.py`
- Create: `tests/unit/test_extractor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_extractor.py`:

```python
import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.extractor import extract_candidate
from recruiter.schemas.extraction import ExtractedCandidate


@pytest.mark.asyncio
async def test_extract_candidate_calls_llm_with_text_and_returns_struct() -> None:
    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice Doe", email="alice@example.com", skills=["Python", "Rust"])
        ]
    )
    result = await extract_candidate(text="Alice Doe — alice@example.com — Python, Rust", llm=fake)
    assert result.full_name == "Alice Doe"
    assert "Rust" in result.skills

    sent = fake.calls[0]
    assert sent["kind"] == "structured"
    assert sent["schema"] == "ExtractedCandidate"
    user_msg = next(m for m in sent["messages"] if m.role == "user")
    assert "Alice Doe" in user_msg.content


@pytest.mark.asyncio
async def test_extract_candidate_returns_empty_on_blank_text() -> None:
    fake = FakeLLMClient()
    result = await extract_candidate(text="", llm=fake)
    assert result.full_name is None
    assert result.skills == []
    assert fake.calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_extractor.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement extractor**

Create `src/recruiter/pipeline/extractor.py`:

```python
from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate

_SYSTEM = """You are a resume and profile parser. Given raw text from a resume, profile, or web page,
extract structured information about the candidate. Be conservative — leave fields null/empty when
not clearly stated. Do not invent skills or experience. Output JSON only matching the requested schema."""


async def extract_candidate(*, text: str, llm: LLMClient) -> ExtractedCandidate:
    if not text.strip():
        return ExtractedCandidate()
    user = f"Raw candidate text:\n\n{text}\n\nReturn the structured JSON."
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=ExtractedCandidate,
        system=_SYSTEM,
        max_tokens=4096,
        temperature=0.0,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_extractor.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/extractor.py tests/unit/test_extractor.py
git commit -m "feat(pipeline): add LLM-based candidate extractor"
```

---

## Task 18: Pipeline Scorer

**Files:**
- Create: `src/recruiter/pipeline/scorer.py`
- Create: `tests/unit/test_scorer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scorer.py`:

```python
import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.scorer import score_candidate
from recruiter.schemas.candidate import ExperienceItem
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult
from recruiter.schemas.job import CriteriaItem


@pytest.mark.asyncio
async def test_score_candidate_calls_llm_with_jd_criteria_and_candidate() -> None:
    candidate = ExtractedCandidate(
        full_name="Alice",
        skills=["Python", "Rust"],
        experience=[ExperienceItem(title="Senior Backend", company="Acme", start="2020", end="2024")],
    )
    criteria = [CriteriaItem(name="Rust", weight=0.6, description="2+ years"), CriteriaItem(name="APIs", weight=0.4, description="REST/gRPC")]
    expected = ScoreResult(
        score=82,
        breakdown=[
            ScoreBreakdownItem(criterion="Rust", weight=0.6, score=80, rationale="Strong Rust signal"),
            ScoreBreakdownItem(criterion="APIs", weight=0.4, score=85, rationale="Backend exp"),
        ],
        rationale="Solid backend with Rust",
    )
    fake = FakeLLMClient(structured_responses=[expected])

    result = await score_candidate(
        job_title="Backend Engineer",
        job_description="Build Rust APIs",
        criteria=criteria,
        candidate=candidate,
        llm=fake,
    )
    assert result.score == 82
    assert len(result.breakdown) == 2

    sent = fake.calls[0]
    user_msg = next(m for m in sent["messages"] if m.role == "user")
    assert "Backend Engineer" in user_msg.content
    assert "Rust" in user_msg.content
    assert "Alice" in user_msg.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_scorer.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement scorer**

Create `src/recruiter/pipeline/scorer.py`:

```python
import json

from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate, ScoreResult
from recruiter.schemas.job import CriteriaItem

_SYSTEM = """You are a recruiting evaluator. Score the candidate against the job description and weighted criteria.

For each criterion, return a 0-100 score and a one-sentence rationale. The overall score is a weighted average,
rounded to an integer. Be honest and specific. Avoid generic statements. If the candidate is missing evidence
for a criterion, score low and say what is missing.

Output JSON only matching the requested schema."""


async def score_candidate(
    *,
    job_title: str,
    job_description: str,
    criteria: list[CriteriaItem],
    candidate: ExtractedCandidate,
    llm: LLMClient,
) -> ScoreResult:
    criteria_payload = [c.model_dump() for c in criteria]
    candidate_payload = candidate.model_dump()
    user = (
        f"Job title: {job_title}\n\n"
        f"Job description:\n{job_description}\n\n"
        f"Weighted criteria (weights sum to 1.0):\n{json.dumps(criteria_payload, ensure_ascii=False, indent=2)}\n\n"
        f"Candidate:\n{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}\n\n"
        "Return the structured score JSON."
    )
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=ScoreResult,
        system=_SYSTEM,
        max_tokens=4096,
        temperature=0.0,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_scorer.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/scorer.py tests/unit/test_scorer.py
git commit -m "feat(pipeline): add LLM-based candidate scorer"
```

---

## Task 19: Pipeline Orchestrator

**Files:**
- Create: `src/recruiter/events.py`
- Create: `src/recruiter/pipeline/orchestrator.py`
- Create: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_orchestrator.py`:

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.events import EventBus
from recruiter.llm.client import FakeLLMClient
from recruiter.models import Application, Candidate, Job, Stage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_process_application_extracts_scores_and_advances_stage(db_session_with_schema: AsyncSession) -> None:
    job = Job(title="Backend", description="Rust APIs", criteria=[{"name": "Rust", "weight": 1.0, "description": "yrs"}])
    candidate = Candidate(full_name=None)
    db_session_with_schema.add_all([job, candidate])
    await db_session_with_schema.flush()

    app = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    db_session_with_schema.add(app)
    await db_session_with_schema.commit()

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="a@b.c", skills=["Rust"]),
            ScoreResult(
                score=85,
                breakdown=[ScoreBreakdownItem(criterion="Rust", weight=1.0, score=85, rationale="ok")],
                rationale="great",
            ),
        ]
    )
    bus = EventBus()
    events: list[dict] = []
    async def listener(payload: dict) -> None:
        events.append(payload)
    bus.subscribe(listener)

    routed = RoutedInput(kind="paste", text="Alice — Rust", source_url=None, resume_path=None)

    engine = db_session_with_schema.bind
    assert engine is not None
    await process_application(
        application_id=app.id,
        routed=routed,
        engine=engine,  # type: ignore[arg-type]
        llm=fake,
        bus=bus,
    )

    # Orchestrator commits via its own session; refresh ours so we re-read from DB.
    await db_session_with_schema.refresh(app)
    await db_session_with_schema.refresh(candidate)

    assert app.stage == Stage.SCORED
    assert app.score == 85
    assert candidate.full_name == "Alice"

    stage_events = [e["stage"] for e in events]
    assert stage_events == ["extracting", "scored"]
```

- [ ] **Step 2: Implement EventBus**

Create `src/recruiter/events.py`:

```python
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

Listener = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self._lock = asyncio.Lock()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                await fn(event)
            except Exception:
                pass
```

- [ ] **Step 3: Implement orchestrator**

Create `src/recruiter/pipeline/orchestrator.py`:

```python
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, EventLog, Job, Stage
from recruiter.pipeline.extractor import extract_candidate
from recruiter.pipeline.router import RoutedInput
from recruiter.pipeline.scorer import score_candidate
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.job import CriteriaItem


async def process_application(
    *,
    application_id: int,
    routed: RoutedInput,
    engine: AsyncEngine,
    llm: LLMClient,
    bus: EventBus,
) -> None:
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as session:
        app = await session.get(Application, application_id)
        if app is None:
            return
        job = await session.get(Job, app.job_id)
        candidate = await session.get(Candidate, app.candidate_id)
        if job is None or candidate is None:
            return

        await bus.publish({"type": "stage", "application_id": app.id, "stage": Stage.EXTRACTING.value})

        text = routed.text or ""
        try:
            extracted = await extract_candidate(text=text, llm=llm)
        except Exception as exc:
            session.add(EventLog(application_id=app.id, event_type="extract.failed", payload={"error": str(exc)}))
            await session.commit()
            await bus.publish({"type": "error", "application_id": app.id, "phase": "extract", "error": str(exc)})
            return

        _apply_extracted(candidate, extracted, raw_text=text, source_url=routed.source_url, resume_path=routed.resume_path)
        await session.flush()

        criteria = [CriteriaItem.model_validate(c) for c in (job.criteria or [])]
        try:
            score = await score_candidate(
                job_title=job.title,
                job_description=job.description,
                criteria=criteria,
                candidate=extracted,
                llm=llm,
            )
        except Exception as exc:
            session.add(EventLog(application_id=app.id, event_type="score.failed", payload={"error": str(exc)}))
            await session.commit()
            await bus.publish({"type": "error", "application_id": app.id, "phase": "score", "error": str(exc)})
            return

        app.score = score.score
        app.score_breakdown = [item.model_dump() for item in score.breakdown]
        app.score_rationale = score.rationale
        app.stage = Stage.SCORED
        session.add(EventLog(application_id=app.id, event_type="application.scored", payload={"score": score.score}))
        await session.commit()

    await bus.publish({"type": "stage", "application_id": application_id, "stage": Stage.SCORED.value, "score": score.score})


def _apply_extracted(
    candidate: Candidate,
    extracted: ExtractedCandidate,
    *,
    raw_text: str,
    source_url: str | None,
    resume_path: str | None,
) -> None:
    candidate.full_name = extracted.full_name or candidate.full_name
    candidate.email = extracted.email or candidate.email
    candidate.phone = extracted.phone or candidate.phone
    candidate.location = extracted.location or candidate.location
    candidate.headline = extracted.headline or candidate.headline
    candidate.summary = extracted.summary or candidate.summary
    if extracted.skills:
        candidate.skills = extracted.skills
    if extracted.experience:
        candidate.experience = [item.model_dump() for item in extracted.experience]
    if extracted.education:
        candidate.education = [item.model_dump() for item in extracted.education]
    if extracted.links:
        candidate.links = [item.model_dump() for item in extracted.links]
    candidate.raw_extracted = {"text": raw_text, "structured": extracted.model_dump()}
    if source_url is not None:
        candidate.source_url = source_url
    if resume_path is not None:
        candidate.resume_path = resume_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_orchestrator.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/events.py src/recruiter/pipeline/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(pipeline): add orchestrator that runs extract → score and emits events"
```

---

## Task 20: API — Jobs CRUD

**Files:**
- Create: `src/recruiter/api/__init__.py`
- Create: `src/recruiter/api/deps.py`
- Create: `src/recruiter/api/jobs.py`
- Modify: `src/recruiter/main.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_jobs_api.py`

- [ ] **Step 1: Write the shared API test fixture**

Create `tests/api/__init__.py` (empty file).

Create `tests/api/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from recruiter.api.deps import get_session
from recruiter.main import app
from recruiter.models import Base


@pytest.fixture
async def api_client(pg_dsn: str) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(pg_dsn)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncIterator:
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
```

Create `tests/api/test_jobs_api.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_list_jobs(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/jobs",
        json={"title": "Backend", "description": "Rust APIs", "criteria": []},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["title"] == "Backend"
    assert job["status"] == "open"

    listing = await api_client.get("/api/jobs")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


@pytest.mark.asyncio
async def test_get_job_returns_404_when_missing(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/jobs/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_job(api_client: AsyncClient) -> None:
    created = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()
    resp = await api_client.patch(f"/api/jobs/{created['id']}", json={"title": "T2"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "T2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_jobs_api.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement deps and Jobs router**

Create `src/recruiter/api/__init__.py` (empty file).

Create `src/recruiter/api/deps.py`:

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruiter.config import get_config
from recruiter.db import get_engine


async def get_session() -> AsyncIterator[AsyncSession]:
    engine = get_engine(get_config().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
```

Create `src/recruiter/api/jobs.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session
from recruiter.models import Job, JobStatus
from recruiter.schemas.job import JobCreate, JobRead, JobUpdate

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, session: AsyncSession = Depends(get_session)) -> JobRead:
    job = Job(
        title=payload.title,
        description=payload.description,
        criteria=[c.model_dump() for c in payload.criteria],
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return _to_read(job)


@router.get("", response_model=list[JobRead])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[JobRead]:
    rows = (await session.execute(select(Job).order_by(Job.created_at.desc()))).scalars().all()
    return [_to_read(j) for j in rows]


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: int, session: AsyncSession = Depends(get_session)) -> JobRead:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_read(job)


@router.patch("/{job_id}", response_model=JobRead)
async def update_job(
    job_id: int, payload: JobUpdate, session: AsyncSession = Depends(get_session)
) -> JobRead:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if payload.title is not None:
        job.title = payload.title
    if payload.description is not None:
        job.description = payload.description
    if payload.criteria is not None:
        job.criteria = [c.model_dump() for c in payload.criteria]
    if payload.status is not None:
        job.status = JobStatus(payload.status)
    await session.commit()
    await session.refresh(job)
    return _to_read(job)


def _to_read(job: Job) -> JobRead:
    return JobRead(
        id=job.id,
        title=job.title,
        description=job.description,
        criteria=job.criteria,
        status=job.status.value,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
```

Overwrite `src/recruiter/main.py`:

```python
from fastapi import FastAPI

from recruiter.api import jobs

app = FastAPI(title="Recruiter Agent")
app.include_router(jobs.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_jobs_api.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api src/recruiter/main.py tests/api
git commit -m "feat(api): add Jobs CRUD endpoints"
```

---

## Task 21: API — Add Candidate from URL

**Files:**
- Create: `src/recruiter/api/candidates.py`
- Modify: `src/recruiter/main.py`
- Create: `tests/api/test_candidates_url_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_candidates_url_api.py`:

```python
import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_add_candidate_via_paste_runs_pipeline(api_client: AsyncClient) -> None:
    job_resp = await api_client.post(
        "/api/jobs",
        json={"title": "Backend", "description": "Rust APIs", "criteria": [{"name": "Rust", "weight": 1.0, "description": "yrs"}]},
    )
    job_id = job_resp.json()["id"]

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="a@b.c", skills=["Rust"]),
            ScoreResult(
                score=88,
                breakdown=[ScoreBreakdownItem(criterion="Rust", weight=1.0, score=88, rationale="strong")],
                rationale="great",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        resp = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "paste", "content": "Alice — Rust"},
        )
        assert resp.status_code == 202, resp.text
        application_id = resp.json()["application_id"]

        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{application_id}")
            if r.json()["stage"] == "scored":
                break

        final = await api_client.get(f"/api/applications/{application_id}")
        body = final.json()
        assert body["stage"] == "scored"
        assert body["score"] == 88
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_add_candidate_via_linkedin_url_stays_extracting_until_paste(api_client: AsyncClient) -> None:
    job_resp = await api_client.post(
        "/api/jobs",
        json={"title": "T", "description": "D", "criteria": []},
    )
    job_id = job_resp.json()["id"]

    fake = FakeLLMClient()  # no responses queued — should not be called
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        resp = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "url", "url": "https://www.linkedin.com/in/alice/"},
        )
        assert resp.status_code == 202
        application_id = resp.json()["application_id"]

        await asyncio.sleep(0.1)
        r = await api_client.get(f"/api/applications/{application_id}")
        body = r.json()
        assert body["stage"] == "extracting"
        assert fake.calls == []
    finally:
        app.dependency_overrides.pop(get_llm, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_candidates_url_api.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement candidates router with URL + paste**

Create `src/recruiter/api/candidates.py`:

```python
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from recruiter.api.deps import get_session
from recruiter.config import get_config
from recruiter.db import get_engine
from recruiter.events import EventBus
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, Job, SourceType, Stage
from recruiter.pipeline.fetchers.github import fetch_github
from recruiter.pipeline.fetchers.linkedin_stub import fetch_linkedin
from recruiter.pipeline.fetchers.webpage import fetch_webpage
from recruiter.pipeline.orchestrator import process_application
from recruiter.pipeline.router import RoutedInput, classify_url

router = APIRouter(prefix="/api/jobs/{job_id}/candidates", tags=["candidates"])


_singleton_bus = EventBus()


def get_event_bus() -> EventBus:
    return _singleton_bus


def get_llm() -> LLMClient:
    raise HTTPException(status_code=500, detail="LLM client not configured for this environment")


def get_engine_dep() -> AsyncEngine:
    return get_engine(get_config().database_url)


class CandidateCreateUrl(BaseModel):
    kind: Literal["url"]
    url: str


class CandidateCreatePaste(BaseModel):
    kind: Literal["paste"]
    content: str
    source_url: str | None = None


class ApplicationCreated(BaseModel):
    application_id: int


@router.post("", response_model=ApplicationCreated, status_code=status.HTTP_202_ACCEPTED)
async def add_candidate(
    job_id: int,
    payload: CandidateCreateUrl | CandidateCreatePaste,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    if payload.kind == "url":
        routed = await _route_url(payload.url)
        source_type = SourceType.URL
        source_url = payload.url
    else:
        routed = RoutedInput(kind="paste", text=payload.content, source_url=payload.source_url, resume_path=None)
        source_type = SourceType.PASTE
        source_url = payload.source_url

    candidate = Candidate(source_type=source_type, source_url=source_url)
    session.add(candidate)
    await session.flush()

    application = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    session.add(application)
    await session.commit()
    await session.refresh(application)

    if routed.kind == "linkedin":
        return ApplicationCreated(application_id=application.id)

    background_tasks.add_task(
        process_application,
        application_id=application.id,
        routed=routed,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application.id)


async def _route_url(url: str) -> RoutedInput:
    kind = classify_url(url)
    if kind == "github":
        parsed = await fetch_github(url)
        return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)
    if kind == "linkedin":
        parsed = fetch_linkedin(url)
        return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)
    parsed = await fetch_webpage(url)
    return RoutedInput(kind=kind, text=parsed.text, source_url=url, resume_path=None)
```

Overwrite `src/recruiter/main.py`:

```python
from fastapi import FastAPI

from recruiter.api import candidates, jobs

app = FastAPI(title="Recruiter Agent")
app.include_router(jobs.router)
app.include_router(candidates.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Note: `tests/api/test_candidates_url_api.py` references `GET /api/applications/{id}` which is implemented in Task 24. Keep that test deferred — for this task, run only the first half (paste) once Task 24 lands. Adjust:

- For now, mark the second test as `@pytest.mark.skip(reason="depends on applications endpoint, see Task 24")` if needed during incremental work, OR run both once Task 24 is done. Either way, leave the test code as written.

- [ ] **Step 4: Run test (deferred — full test passes after Task 24 lands)**

Run: `python -m pytest tests/api/test_candidates_url_api.py -v`
Expected: import succeeds; tests will fully pass once Task 24 is implemented. If running mid-plan, mark with `@pytest.mark.skip` until Task 24 is complete.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/candidates.py src/recruiter/main.py tests/api/test_candidates_url_api.py
git commit -m "feat(api): add candidate creation via URL and paste"
```

---

## Task 22: API — Add Candidate from Resume Upload

**Files:**
- Modify: `src/recruiter/api/candidates.py`
- Create: `tests/api/test_candidates_upload_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_candidates_upload_api.py`:

```python
import asyncio
from pathlib import Path

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult

PDF_FIXTURE = Path(__file__).parent.parent / "fixtures/resumes/sample.pdf"


@pytest.mark.asyncio
async def test_upload_pdf_resume_runs_pipeline(api_client: AsyncClient) -> None:
    job_resp = await api_client.post(
        "/api/jobs",
        json={"title": "Backend", "description": "Rust", "criteria": []},
    )
    job_id = job_resp.json()["id"]

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", skills=["Rust"]),
            ScoreResult(score=70, breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")], rationale="ok"),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        with PDF_FIXTURE.open("rb") as fh:
            resp = await api_client.post(
                f"/api/jobs/{job_id}/candidates/upload",
                files={"file": ("resume.pdf", fh, "application/pdf")},
            )
        assert resp.status_code == 202, resp.text
        application_id = resp.json()["application_id"]

        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{application_id}")
            if r.json()["stage"] == "scored":
                break

        final = await api_client.get(f"/api/applications/{application_id}")
        assert final.json()["stage"] == "scored"
        assert final.json()["score"] == 70
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_upload_unsupported_type_returns_400(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]
    resp = await api_client.post(
        f"/api/jobs/{job_id}/candidates/upload",
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 415
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_candidates_upload_api.py -v`
Expected: FAIL — endpoint not defined.

- [ ] **Step 3: Add upload endpoint**

Edit `src/recruiter/api/candidates.py` — append the following to the file (after the existing `add_candidate` function and `_route_url` helper):

```python
import os
import uuid
from pathlib import Path

from fastapi import File, UploadFile

from recruiter.pipeline.parsers.docx import parse_docx
from recruiter.pipeline.parsers.pdf import parse_pdf


@router.post("/upload", response_model=ApplicationCreated, status_code=status.HTTP_202_ACCEPTED)
async def upload_resume(
    job_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    data = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".pdf"):
        parsed = parse_pdf(data)
        kind = "pdf"
    elif name.endswith(".docx"):
        parsed = parse_docx(data)
        kind = "docx"
    else:
        raise HTTPException(status_code=415, detail="only .pdf and .docx are accepted")

    storage_dir = Path(get_config().resume_storage_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"{uuid.uuid4().hex}_{os.path.basename(name)}"
    stored_path.write_bytes(data)

    candidate = Candidate(source_type=SourceType.RESUME, resume_path=str(stored_path))
    session.add(candidate)
    await session.flush()
    application = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.EXTRACTING)
    session.add(application)
    await session.commit()
    await session.refresh(application)

    routed = RoutedInput(kind=kind, text=parsed.text, source_url=None, resume_path=str(stored_path))
    background_tasks.add_task(
        process_application,
        application_id=application.id,
        routed=routed,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application.id)
```

- [ ] **Step 4: Run test to verify it passes (after Task 24 lands for the first test)**

Run: `python -m pytest tests/api/test_candidates_upload_api.py -v`
Expected: import succeeds; first test fully passes after Task 24; second test (415 case) passes immediately.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/candidates.py tests/api/test_candidates_upload_api.py
git commit -m "feat(api): add resume upload endpoint (PDF, DOCX)"
```

---

## Task 23: API — Re-extract After LinkedIn Paste

**Files:**
- Modify: `src/recruiter/api/candidates.py`
- Create: `tests/api/test_linkedin_paste_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_linkedin_paste_api.py`:

```python
import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_paste_content_for_linkedin_application_runs_pipeline(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]

    fake = FakeLLMClient()
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        create = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            json={"kind": "url", "url": "https://www.linkedin.com/in/alice/"},
        )
        application_id = create.json()["application_id"]

        fake._structured.append(ExtractedCandidate(full_name="Alice", skills=["Rust"]))
        fake._structured.append(
            ScoreResult(score=60, breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=60, rationale="ok")], rationale="ok")
        )

        resp = await api_client.post(
            f"/api/applications/{application_id}/paste",
            json={"content": "Alice — pasted from LinkedIn — Rust"},
        )
        assert resp.status_code == 202

        for _ in range(50):
            await asyncio.sleep(0.05)
            r = await api_client.get(f"/api/applications/{application_id}")
            if r.json()["stage"] == "scored":
                break
        assert r.json()["stage"] == "scored"
    finally:
        app.dependency_overrides.pop(get_llm, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_linkedin_paste_api.py -v`
Expected: FAIL — endpoint not defined.

- [ ] **Step 3: Implement the paste endpoint**

Edit `src/recruiter/api/candidates.py` — append:

```python
class PastePayload(BaseModel):
    content: str


paste_router = APIRouter(prefix="/api/applications", tags=["applications"])


@paste_router.post("/{application_id}/paste", response_model=ApplicationCreated, status_code=status.HTTP_202_ACCEPTED)
async def paste_content(
    application_id: int,
    payload: PastePayload,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    bus: EventBus = Depends(get_event_bus),
) -> ApplicationCreated:
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="application not found")
    if application.stage != Stage.EXTRACTING:
        raise HTTPException(status_code=409, detail=f"cannot paste in stage {application.stage.value}")

    routed = RoutedInput(kind="paste", text=payload.content, source_url=None, resume_path=None)
    background_tasks.add_task(
        process_application,
        application_id=application_id,
        routed=routed,
        engine=engine,
        llm=llm,
        bus=bus,
    )
    return ApplicationCreated(application_id=application_id)
```

Edit `src/recruiter/main.py` to add the paste_router:

Overwrite `src/recruiter/main.py`:

```python
from fastapi import FastAPI

from recruiter.api import candidates, jobs

app = FastAPI(title="Recruiter Agent")
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(candidates.paste_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_linkedin_paste_api.py -v`
Expected: 1 PASSED (after Task 24 lands, since this test reads `/api/applications/{id}`).

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/candidates.py src/recruiter/main.py tests/api/test_linkedin_paste_api.py
git commit -m "feat(api): add paste endpoint to feed content into a pending application"
```

---

## Task 24: API — Applications Read

**Files:**
- Create: `src/recruiter/api/applications.py`
- Modify: `src/recruiter/main.py`
- Create: `tests/api/test_applications_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_applications_api.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_application_returns_404_when_missing(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/applications/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_applications_for_job(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]

    listing = await api_client.get(f"/api/jobs/{job_id}/applications")
    assert listing.status_code == 200
    assert listing.json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_applications_api.py -v`
Expected: FAIL — endpoint not defined.

- [ ] **Step 3: Implement applications router**

Create `src/recruiter/api/applications.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session
from recruiter.models import Application
from recruiter.schemas.application import ApplicationRead

router = APIRouter(prefix="/api", tags=["applications"])


@router.get("/applications/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: int, session: AsyncSession = Depends(get_session)) -> ApplicationRead:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return _to_read(app_row)


@router.get("/jobs/{job_id}/applications", response_model=list[ApplicationRead])
async def list_applications_for_job(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> list[ApplicationRead]:
    rows = (
        await session.execute(
            select(Application).where(Application.job_id == job_id).order_by(Application.created_at.desc())
        )
    ).scalars().all()
    return [_to_read(r) for r in rows]


def _to_read(app_row: Application) -> ApplicationRead:
    return ApplicationRead(
        id=app_row.id,
        job_id=app_row.job_id,
        candidate_id=app_row.candidate_id,
        stage=app_row.stage.value,
        score=app_row.score,
        score_breakdown=app_row.score_breakdown,
        score_rationale=app_row.score_rationale,
        notes=app_row.notes,
        validated_at=app_row.validated_at,
        invited_at=app_row.invited_at,
        scheduled_at=app_row.scheduled_at,
        rejected_at=app_row.rejected_at,
        created_at=app_row.created_at,
        updated_at=app_row.updated_at,
    )
```

Overwrite `src/recruiter/main.py`:

```python
from fastapi import FastAPI

from recruiter.api import applications, candidates, jobs

app = FastAPI(title="Recruiter Agent")
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(candidates.paste_router)
app.include_router(applications.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_applications_api.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Run all the previously-deferred tests**

Run: `python -m pytest tests/api -v`
Expected: All pass — Task 21, 22, 23 tests now pass since `/api/applications/{id}` exists.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/api/applications.py src/recruiter/main.py tests/api/test_applications_api.py
git commit -m "feat(api): add applications read endpoints"
```

---

## Task 25: API — Settings

**Files:**
- Create: `src/recruiter/api/settings.py`
- Modify: `src/recruiter/main.py`
- Create: `tests/api/test_settings_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_settings_api.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_settings_default_when_unset(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_llm_provider"] == "anthropic"
    assert body["has_anthropic_api_key"] is False


@pytest.mark.asyncio
async def test_update_settings_encrypts_secret(api_client: AsyncClient) -> None:
    resp = await api_client.put(
        "/api/settings",
        json={"anthropic_api_key": "sk-ant-test", "recruiter_email": "me@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_anthropic_api_key"] is True
    assert "sk-ant-test" not in resp.text  # secret is not echoed
    assert body["recruiter_email"] == "me@example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_settings_api.py -v`
Expected: FAIL — endpoint not defined.

- [ ] **Step 3: Implement settings router**

Create `src/recruiter/api/settings.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session
from recruiter.config import get_config
from recruiter.crypto import SecretCipher
from recruiter.models import SettingsRow
from recruiter.schemas.settings import SettingsRead, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _cipher() -> SecretCipher:
    raw = get_config().settings_key
    # Accept either a 32-byte raw string or a 64-char hex-encoded string. No silent padding.
    if len(raw) == 64:
        try:
            key = bytes.fromhex(raw)
        except ValueError as exc:
            raise RuntimeError("RECRUITER_SETTINGS_KEY: 64-char value must be valid hex") from exc
    else:
        key = raw.encode("utf-8")
    if len(key) != 32:
        raise RuntimeError(
            "RECRUITER_SETTINGS_KEY must be 32 bytes (or 64 hex chars). "
            "Generate with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    return SecretCipher(key)


async def _load_or_create(session: AsyncSession) -> SettingsRow:
    row = (await session.execute(select(SettingsRow).where(SettingsRow.id == 1))).scalar_one_or_none()
    if row is None:
        row = SettingsRow(id=1, default_llm_provider="anthropic")
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def _to_read(row: SettingsRow) -> SettingsRead:
    return SettingsRead(
        default_llm_provider=row.default_llm_provider,
        has_anthropic_api_key=bool(row.anthropic_api_key_enc),
        local_llm_url=row.local_llm_url,
        model_overrides=row.model_overrides or {},
        has_google_oauth_tokens=bool(row.google_oauth_tokens_enc),
        has_smtp_config=bool(row.smtp_config_enc),
        recruiter_name=row.recruiter_name,
        recruiter_email=row.recruiter_email,
        monthly_llm_spend_cap_usd=row.monthly_llm_spend_cap_usd,
    )


@router.get("", response_model=SettingsRead)
async def get_settings(session: AsyncSession = Depends(get_session)) -> SettingsRead:
    row = await _load_or_create(session)
    return _to_read(row)


@router.put("", response_model=SettingsRead)
async def update_settings(
    payload: SettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> SettingsRead:
    row = await _load_or_create(session)
    cipher = _cipher()
    if payload.default_llm_provider is not None:
        row.default_llm_provider = payload.default_llm_provider
    if payload.anthropic_api_key is not None:
        row.anthropic_api_key_enc = cipher.encrypt(payload.anthropic_api_key)
    if payload.local_llm_url is not None:
        row.local_llm_url = payload.local_llm_url
    if payload.model_overrides is not None:
        row.model_overrides = payload.model_overrides
    if payload.recruiter_name is not None:
        row.recruiter_name = payload.recruiter_name
    if payload.recruiter_email is not None:
        row.recruiter_email = payload.recruiter_email
    if payload.monthly_llm_spend_cap_usd is not None:
        row.monthly_llm_spend_cap_usd = payload.monthly_llm_spend_cap_usd
    await session.commit()
    await session.refresh(row)
    return _to_read(row)
```

Overwrite `src/recruiter/main.py`:

```python
from fastapi import FastAPI

from recruiter.api import applications, candidates, jobs, settings

app = FastAPI(title="Recruiter Agent")
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(candidates.paste_router)
app.include_router(applications.router)
app.include_router(settings.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_settings_api.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/settings.py src/recruiter/main.py tests/api/test_settings_api.py
git commit -m "feat(api): add settings GET/PUT with encrypted secret storage"
```

---

## Task 26: SSE Events Endpoint + Wire Bus into Default DI

**Files:**
- Create: `src/recruiter/api/events.py`
- Modify: `src/recruiter/api/candidates.py` (replace `get_event_bus` to use module-level singleton)
- Modify: `src/recruiter/main.py`
- Create: `tests/api/test_events_sse.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_events_sse.py`:

```python
import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_event_bus, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_sse_emits_stage_events_during_pipeline(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", skills=["Rust"]),
            ScoreResult(score=70, breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")], rationale="ok"),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        bus = get_event_bus()
        events: list[dict] = []

        async def listener(payload: dict) -> None:
            events.append(payload)

        unsub = bus.subscribe(listener)
        try:
            create = await api_client.post(
                f"/api/jobs/{job_id}/candidates",
                json={"kind": "paste", "content": "Alice"},
            )
            application_id = create.json()["application_id"]

            for _ in range(50):
                await asyncio.sleep(0.05)
                if any(e.get("stage") == "scored" for e in events):
                    break
        finally:
            unsub()

        stages = [e["stage"] for e in events if e.get("type") == "stage"]
        assert "extracting" in stages
        assert "scored" in stages
    finally:
        app.dependency_overrides.pop(get_llm, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_events_sse.py -v`
Expected: FAIL — assertion fails or endpoint missing.

- [ ] **Step 3: Implement SSE endpoint**

Create `src/recruiter/api/events.py`:

```python
import asyncio
import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from recruiter.api.candidates import get_event_bus
from recruiter.events import EventBus

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def stream_events(bus: EventBus = Depends(get_event_bus)) -> EventSourceResponse:
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def listener(event: dict) -> None:
        await queue.put(event)

    unsubscribe = bus.subscribe(listener)

    async def event_generator() -> object:
        try:
            while True:
                event = await queue.get()
                yield {"event": event.get("type", "message"), "data": json.dumps(event)}
        finally:
            unsubscribe()

    return EventSourceResponse(event_generator())
```

Overwrite `src/recruiter/main.py`:

```python
from fastapi import FastAPI

from recruiter.api import applications, candidates, events, jobs, settings

app = FastAPI(title="Recruiter Agent")
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(candidates.paste_router)
app.include_router(applications.router)
app.include_router(settings.router)
app.include_router(events.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_events_sse.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -v`
Expected: All tests pass.

- [ ] **Step 6: Final smoke test against live LLM (manual, opt-in)**

Manual:
```bash
docker compose up -d postgres
alembic upgrade head
export RECRUITER_DATABASE_URL=postgresql+asyncpg://recruiter:recruiter@localhost:5432/recruiter
export RECRUITER_ANTHROPIC_API_KEY=sk-ant-...
uvicorn recruiter.main:app --reload
```

In another shell:
```bash
# Configure LLM via settings
curl -X PUT http://localhost:8000/api/settings -H 'content-type: application/json' \
  -d '{"anthropic_api_key":"'"$RECRUITER_ANTHROPIC_API_KEY"'"}'

# Note: the live LLM is wired by overriding get_llm in main.py during real serving — see follow-up task
```

(Live wiring of the LLM dependency in production happens once Plan B / a startup-config phase lands. For Plan A, all tests pass with `FakeLLMClient`.)

- [ ] **Step 7: Commit**

```bash
git add src/recruiter/api/events.py src/recruiter/main.py tests/api/test_events_sse.py
git commit -m "feat(api): add SSE endpoint streaming pipeline stage events"
```

---

## Self-Review Checklist (run after writing the plan)

- [x] Spec coverage:
  - Sources (URL routing + PDF + DOCX + paste): Tasks 10–16, 21, 22, 23
  - Pluggable LLM (Anthropic + OpenAI-compat): Tasks 7, 8, 9
  - Job + criteria scoring: Tasks 4, 6, 18
  - Multi-job kanban data shape: Tasks 4, 24
  - Candidate model + raw_extracted: Tasks 4, 19
  - Application stages enum incl. unused `sourced`: Task 4
  - Notification + Settings + EventLog schemas: Task 5 (functional Notification wiring is Plan C)
  - Encrypted-at-rest secrets: Tasks 3, 25
  - SSE for live updates: Tasks 19, 26
  - BackgroundTasks for async: Tasks 21, 22, 23
- [x] No placeholders ("TBD", "TODO", "fill in") found in steps.
- [x] Type consistency: `RoutedInput`, `EventBus`, `LLMClient`, `LLMMessage`, `ExtractedCandidate`, `ScoreResult`, `Stage` enum used consistently across tasks.
- [x] Open caveats:
  - Tasks 21–23 reference `GET /api/applications/{id}` which is implemented in Task 24; the test files are written upfront but the deferred tests fully pass after Task 24 lands.
  - Live wiring of `get_llm` (binding Anthropic/OpenAI-compat to settings at startup) is intentionally deferred to a small follow-up at the start of Plan B, since it requires app startup hooks reading from `Settings`. Plan A's test suite passes entirely with `FakeLLMClient` injected via `dependency_overrides`.

---

## End State

After Task 26:

- A FastAPI server with health, jobs CRUD, add-candidate (URL/upload/paste), applications read, settings, and SSE.
- A pipeline that, given a fake or real LLM, extracts a candidate from raw text and scores them against a job's JD + weighted criteria.
- A test suite covering parsers, fetchers, extractor, scorer, orchestrator, and all API surfaces — all green against a real Postgres (testcontainers) with a fake LLM client.
- An Alembic migration history that any new clone can run via `alembic upgrade head`.

The next plan (B) wires the React dashboard to this API, including live wiring of the LLM provider from Settings at app startup.

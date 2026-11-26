# Backend Development Guide for AI Agents & Engineers

This document provides architecture conventions, standards, and guidelines for developing backend services, database interactions, and agent pipelines in this repository.

---

## 1. Tech Stack & Core Architecture

- **Framework**: FastAPI (async ASGI)
- **Database Engine**: PostgreSQL (hosted on Supabase)
- **Database Driver**: `asyncpg` (`postgresql+asyncpg://...`)
- **ORM / Query Builder**: SQLAlchemy 2.0 (pure async paradigm)
- **Validation & Settings**: Pydantic v2 & `pydantic-settings`
- **Package Management**: `pip` / `requirements.txt` / `pyproject.toml`

---

## 2. Database Standards & Supabase Integration

### Connection Paradigm: Pure Async

- **Driver**: All database communication must strictly use `asyncpg`. Never use blocking drivers (`psycopg2`, synchronous sqlite, etc.) in production paths.
- **Connection Strings**:
  - Direct connection:
    ```bash
    DATABASE_URL="postgresql+asyncpg://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres"
    ```
  - Supabase Connection Pooler (Supavisor / Transaction mode):
    ```bash
    DATABASE_URL="postgresql+asyncpg://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres"
    ```

### Session Lifecycle & Safety Rules

1. **No Auto Schema Generation on Startup**:
   - `Base.metadata.create_all` is deliberately **not** called on application startup in `lifespan`.
   - Table schemas, migrations, indexes, and triggers must be created deliberately via migrations or Supabase SQL Editor / CLI.
2. **On-Demand Scoped Sessions**:
   - Database sessions must never be held persistently across the lifecycle of an application or module.
   - Use the `get_db()` async generator dependency in FastAPI endpoints or context managers:
     ```python
     from app.db.session import get_db
     from sqlalchemy.ext.asyncio import AsyncSession

     @router.get("/endpoint")
     async def my_endpoint(db: AsyncSession = Depends(get_db)):
         ...
     ```
   - Every session is created on-demand and closed explicitly in its `finally` block:
     ```python
     async def get_db() -> AsyncIterator[AsyncSession]:
         async with AsyncSessionLocal() as session:
             try:
                 yield session
             finally:
                 await session.close()
     ```
3. **Application Lifespan Graceful Cleanup**:
   - Connection pools are disposed of in [`app/main.py`](file:///Users/bhimk/Personal_Repos/AMS_Agent/asm-agentic-incident-management/backend/app/main.py) inside a `try...finally` block to prevent resource leaks during unexpected terminations:
     ```python
     @asynccontextmanager
     async def lifespan(app: FastAPI):
         setup_logging()
         logger.info(f"Starting {settings.PROJECT_NAME} [{settings.ENVIRONMENT}]")
         try:
             yield
         finally:
             logger.info(f"Shutting down {settings.PROJECT_NAME}")
             await close_db()
     ```

### Database Scripts (`db/scripts/`)

Schema is managed by plain SQL scripts that run from a workbench (Supabase SQL Editor, pgAdmin, DBeaver). See [`db/scripts/README.md`](db/scripts/README.md).

- Run in numeric order: `01_create_servicenow_tickets.sql`, then `02_create_dq_rules.sql`. Scripts are idempotent (`IF NOT EXISTS`). `99_drop_tables.sql` is destructive, dev only.
- Add each schema change as the next numbered script (e.g. `03_add_<change>.sql`). Do not edit applied scripts.
- Tables:
  - `servicenow_tickets`: tickets in the AMS team's schema, plus `dq_flag` / `dq_reason`. Tickets are always stored; the flag marks them as filtered out by data quality rules.
  - `dq_rules`: user-managed rules (`field`, `operator`, `value`, optional `source` / `service`, `apply_to` = existing/new/both, `is_enabled` toggle, soft delete via `deleted_at`).
  - `dq_runs`, `dq_run_tickets`: history of rule applies, and per ticket flagged by a run the matching `rule_id` (first match wins) plus `reverted_dq_flag` / `reverted_dq_reason` (restored when the run is reverted).
- Design notes, assumptions and open questions: [`db/scripts/DQ_RULES_FEATURE.md`](db/scripts/DQ_RULES_FEATURE.md).
- Known gap: `app/models/ticket.py` still defines the older `tickets` / `agent_runs` tables and does not match these scripts yet. Update the models and services before using the new tables from code.

---

## 3. Developing Agents & Services

When building agent workers (e.g., triage, data quality, resolution):

1. **Async by Default**:
   Agent orchestration steps and tool executions that query or mutate database records must use `await session.execute(...)`, `await session.get(...)`, and `await session.commit()`.
2. **Session Scope for Long-Running Tasks / Background Agents**:
   - Do **not** pass a single session into a long-running batch agent process.
   - For long-running worker loops, instantiate isolated scoped sessions via `async with AsyncSessionLocal() as session:` for each unit of work (e.g., per ticket analysis), and commit/close immediately.
3. **Audit Trail**:
   Every agent action should record an entry to the audit log (`agent_runs`) referencing the ticket and logging output verdicts with execution timestamps.

---

## 4. Privacy & PII Masking Standards (Pre-DB Ingestion)

All tickets entering the PostgreSQL database (`servicenow_tickets` table) undergo in-process PII redaction before storage:

1. **Scope & Protected Fields**:
   - Redacted fields: `caller`, `short_description`, `description`, and `resolution_notes`.
   - Engine: Microsoft Presidio Analyzer with `spaCy` NER (`en_core_web_sm`) via `app.privacy.masking.Masker`.
2. **Placeholders & Privacy at Rest**:
   - Detected identities are replaced with irreversible standardized tokens: `<PERSON_n>`, `<EMAIL_n>`, `<PHONE_n>`, `<EMPLOYEE_ID_n>`, `<PAN_n>`, `<AADHAAR_n>`.
   - Batch consistency: Within an upload file, multiple occurrences of the same caller (e.g., "Priya Raman") share the same identifier token (`<PERSON_1>`).
3. **Exclusions & Protected Entities**:
   - **System Accounts**: Configured in `data/registry/pii.yaml` (e.g., `Service Desk`, `Integration User`) are preserved untouched.
   - **Application Names**: Applications in `data/registry/apps.yaml` (e.g., `PayrollPro`, `OrderHub`, `TimeTrack`) and error codes (e.g., `ORA-01555`) are protected from accidental masking.
   - **Existing Placeholders**: Pre-existing `<PLACEHOLDER>` strings are excluded from registered known names to prevent false-positive leak errors in downstream checks.
4. **Configuration & Override**:
   - Default: `PII_MASKING_ENABLED = True` in `app.core.config.Settings`.
   - Can be toggled dynamically by admins via `ADMIN_EDITABLE` or passed explicitly in ingestion services (`mask_pii=False`).

---

## 5. Configuration Reference

Database settings are configured in [`app/core/config.py`](file:///Users/bhimk/Personal_Repos/AMS_Agent/asm-agentic-incident-management/backend/app/core/config.py) and populated via `.env`:

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Async PostgreSQL connection string | `postgresql+asyncpg://...` |
| `DB_POOL_SIZE` | SQLAlchemy connection pool size | `5` |
| `DB_MAX_OVERFLOW` | Max extra overflow connections | `10` |
| `DB_POOL_PRE_PING`| Validates connection health before checkout | `True` |
| `DB_ECHO` | Print SQL statements to log (debug only) | `False` |
| `PII_MASKING_ENABLED` | Redact personal information before DB persistence | `True` |
| `SESSION_HOURS` | How long a sign-in lasts (see section 9) | `12` |
| `SESSION_COOKIE_SECURE` | Send the session cookie over HTTPS only | `False` |
| `PHOENIX_ENABLED` | Export API request traces to Arize Phoenix (see section 8) | `False` |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix OTLP/HTTP traces endpoint | `http://localhost:6006/v1/traces` |
| `PHOENIX_PROJECT_NAME` | Project name shown in Phoenix | `ams-incident-management` |

---

## 6. Development Checklist for Agents

When implementing new endpoints, services, or agent tasks:
- [ ] Ensure new models subclass `Base` from `app.db.session`.
- [ ] Avoid `run_sync` or synchronous database calls in async request paths.
- [ ] Explicitly commit transactions (`await db.commit()`) or rollback on error (`await db.rollback()`).
- [ ] Use `select()`, `update()`, and `delete()` SQLAlchemy 2.0 executable statements.
- [ ] Ensure sensitive fields pass through `Masker` before storing in persistent tables.
- [ ] Keep `.env.example` updated when introducing new environment variables.

---

## 7. Resolution Agent: Knowledge Base Index

Runbooks in `data/knowledge_base/*.md` are chunked, contextualised and indexed in `kb_chunks` (`backend/db/scripts/04_create_kb_chunks.sql`).

- **Chunks**: one `### KB-…` issue is one chunk; oversized issues are split with `KB_CHUNK_SIZE` / `KB_CHUNK_OVERLAP` (`app/agents/resolution/chunking.py`).
- **Contextual text**: one short blurb per chunk from `KB_CONTEXT_MODEL` (Haiku), prompt `kb_chunk_context` in `data/registry/prompts.yaml`. Falls back to the app name and heading path when the model is off.
- **Embeddings**: generated outside the app. Implement `Embedder` (`app/agents/resolution/embedding.py`, `google/embeddinggemma-300m`, `EMBEDDING_DIM=256`) and call `embed_pending(embedder)`. Rows stay `embedding IS NULL` until then.
- **Ingest**: `cd backend && ../.venv/bin/python -m app.agents.resolution.ingest`. Unchanged chunks are skipped by `content_hash`.
- **Retrieval**: `retrieve(db, query_text, query_vec, Filters(app=..., kb_id=..., criticality_tier=..., section_type=...))`. Filters are applied first, then dense (pgvector) and full-text search are fused with RRF. Without `query_vec`, full-text search only.

### Resolution run (`POST /api/v1/resolution/run`)

Runs over tickets with `pipeline_status = reviewed`; writes one `agent_runs` row per ticket (`agent = resolution`, verdict `resolved` or `no_match`). Unchanged tickets are skipped by input hash.

- **Filter**: `filters_for(ticket.application)` pre-filters the search to that runbook (`app/agents/resolution/filters.py`).
- **Query transformation**: `expand()` makes a multi-query call (3–5 queries) and a HyDE call in parallel; the ticket summary is always the first query. Without a model: summary only (`queries.py`).
- **ReAct loop**: `resolve()` searches, reads up to 5 excerpts per search, and finishes with `ResolutionAnswer`. Max 4 extra searches. Citations not in the excerpts are sent back to the model (`react.py`, `answer.py`). Rules R1–R3 are in `resolution_react` in `prompts.yaml`.
- **Query vectors**: the endpoint runs full-text only until an `Embedder` is wired in (`run_resolution(embedder=...)`).
- **Model errors**: a ticket whose model call fails gets no `agent_runs` row and is retried on the next run.

---

## 8. Monitoring (Phoenix)

API request traces (method, route, status, latency, `http.request_id`) and LLM call traces (model, prompt, response, tokens, latency) go to Arize Phoenix over OpenTelemetry. Off by default.

- **Enable**: set `PHOENIX_ENABLED=true` in `backend/.env` (`PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_PROJECT_NAME` optional). Not admin-editable.
- **Collector**: `docker compose up phoenix`, then open the UI at http://localhost:6006. Without Docker: `pip install arize-phoenix`, then `phoenix serve` (same port and endpoint).
- **Export**: spans are batched, so they appear in the UI a few seconds after the request. Health check URLs are excluded.
- **Code**: `app/core/telemetry.py`, wired in `app/main.py`. LLM spans come from `openinference-instrumentation-anthropic`, which patches the Anthropic SDK in the same setup. Setup never stops startup; failures are logged as warnings.
- **Privacy**: request spans hold HTTP metadata only. LLM spans hold the prompt and response, but the prompt is built from ticket text that `Masker` already redacted, and the response holds placeholders (`<PERSON_n>`) because unmasking happens after the call. So raw PII is not exported.

---

## 9. Sign-in

Every endpoint except `/health` and `/auth/login` needs a session. Tables: `users`, `user_sessions` (`db/scripts/12_create_users.sql`).

- **Endpoints**: `POST /api/v1/auth/login` (email, password) sets the `ams_session` cookie (HttpOnly, SameSite=Lax); `GET /api/v1/auth/me`; `POST /api/v1/auth/logout`.
- **People**: `cd backend && python scripts/create_user.py <email> "<name as in Jira>" <admin|lead|engineer>` adds a person or changes their name, role or password. `name` must match the Jira display name, because `tickets.assignee` holds it.
- **Storage**: passwords as salted scrypt hashes (standard library); of a session only the SHA-256 of its token. Sessions end after `SESSION_HOURS` or on sign-out.
- **Roles**: `Depends(require_role(...))` from `app/api/v1/endpoints/auth.py`. Admin only: `/demo/reset`, `/admin/*` (as well as the `X-Admin-Key`). Lead or admin: `/tickets/{id}/assign`, `/tickets/{id}/lead-review`. Everything else: any signed-in person.
- **Sign in with Atlassian**: `GET /api/v1/auth/atlassian/start` sends the browser to Atlassian and
  `/auth/atlassian/callback` signs in the user whose email matches the Atlassian account's (`app/services/atlassian_login.py`).
  It only confirms who the person is: they must already be in `users` (`create_user.py ... --atlassian-only` for no
  password), and their role comes from there. Needs `ATLASSIAN_OAUTH_CLIENT_ID` / `ATLASSIAN_OAUTH_CLIENT_SECRET` from an
  OAuth 2.0 (3LO) app at developer.atlassian.com with the User identity API (`read:me`) and `ATLASSIAN_OAUTH_REDIRECT_URI`
  as its callback URL. Without them the console shows no Atlassian button (`GET /auth/providers`).
- **Persona**: an admin can view the console as another person (`GET /api/v1/auth/users` fills the list). This changes the
  console only: the menu, the worklist and the name sent as `by`. The API still sees the admin's own session.
- **Known gap**: the `by` / `reviewer` / `author_email` fields are still taken from the request, not from the session.
- **Tests**: the `client` fixture is signed in as an admin (`current_user` overridden); `tests/test_auth.py` removes that.

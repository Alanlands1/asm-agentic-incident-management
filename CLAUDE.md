# Claude Agent Instructions & Context Guide

Welcome to the **AMS Agentic Incident Management** project.

> **CRITICAL INSTRUCTION**:
> **DO NOT perform recursive codebase-wide searches or inspect every file.**
> Before starting any task, read this document, [`AGENTS.md`](AGENTS.md), and the target subsystem guide.

---

## 1. Project Mental Model

This system implements an automated pipeline for Application Management Services (AMS):
- **Ingestion**: Accepts tickets from ServiceNow (`.xlsx`), JIRA, and Support Mailbox.
- **Data Quality Agent**: Detects missing or malformed fields, sets `dq_flag` and `dq_reason`, and drafts clarification requests.
- **Triage Agent**: Recalculates actual incident priority against business rules.
- **Resolution Agent**: Searches application markdown runbooks (`data/knowledge_base/*.md`) and produces resolution steps.
- **Privacy Layer**: Redacts PII via Presidio before database persistence (at rest) and before LLM model calls.

---

## 2. Source of Truth Documentation

Always consult these documents before modifying or adding code:

| Area | Primary Guide | Key Considerations |
|---|---|---|
| **High-Level Map** | [`AGENTS.md`](AGENTS.md) | Repo layout, architecture diagram, guidelines |
| **Backend / API** | [`backend/DEVELOPMENT.md`](backend/DEVELOPMENT.md) | Pure async FastAPI, SQLAlchemy 2.0 with `asyncpg`, scoped sessions |
| **Database Migrations** | [`backend/db/scripts/DEVELOPMENT.md`](backend/db/scripts/DEVELOPMENT.md) | Sequential SQL numbering (`01_...`, `02_...`), idempotency |
| **Data Quality Logic** | [`backend/db/scripts/DQ_RULES_FEATURE.md`](backend/db/scripts/DQ_RULES_FEATURE.md) | 10 operators, first-match-wins, revert tracking in `dq_run_tickets` |
| **Privacy & Masking** | [`backend/DEVELOPMENT.md`](backend/DEVELOPMENT.md) | Pre-DB Presidio redaction (`caller`, descriptions, notes) |
| **Frontend Dashboard** | [`frontend/DEVELOPMENT.md`](frontend/DEVELOPMENT.md) | Next.js 16 App Router, strict shadcn/ui component usage |
| **Frontend Style** | [`frontend/frontend-guidelines.md`](frontend/frontend-guidelines.md) | No raw Tailwind for pre-existing UI primitives, `@/` aliases |
| **Roadmap & Tasks** | [`TODO.md`](TODO.md) | Task statuses, dependencies, and definitions of done |

---

## 3. Strict Development Rules

1. **Karpathy Guidelines**:
   - **Simplicity First**: Write only what is requested. No premature abstractions or speculative features.
   - **Surgical Changes**: Do not refactor adjacent code, change comments, or reformat untouched files.
   - **Match Existing Style**: Match typing, docstring formats, and error handling patterns.
2. **Database Integrity**:
   - Database tables are defined in [`backend/db/scripts/`](backend/db/scripts/). Do not guess columns.
   - Use `asyncpg` async sessions via `Depends(get_db)`.
   - Never hold long-lived database sessions across batch or agent processing loops.
3. **Frontend Rules**:
   - Do NOT handwrite custom HTML/CSS for buttons, dialogs, badges, inputs, or tables.
   - Always reuse [`frontend/src/components/ui/`](frontend/src/components/ui/) (shadcn/ui primitives).
   - Verify frontend changes using `npm run build` inside `frontend/`.
4. **Backend Testing & Linting**:
   - Verify all backend changes by executing:
     ```bash
     ./.venv/bin/pytest backend/tests/
     ./.venv/bin/ruff check backend/
     ```

---

## 4. Current State & Active Endpoints

- **ServiceNow Ingestion**:
  - Endpoint: `POST /api/v1/servicenow/ingest`
  - Accepts: `multipart/form-data` with `file: UploadFile` (.xlsx only, <= 10MB)
  - Table: `servicenow_tickets` (model: `backend/app/models/servicenow.py`)
  - Behavior: Upserts by `ticket_id`, deduplicates in-file duplicates, respects sheet header for partial column updates.
  - Privacy: Batch Presidio PII redaction on `caller`, `short_description`, `description`, `resolution_notes` before database persistence. Controlled via `PII_MASKING_ENABLED`.
- **Data Quality Endpoints**:
  - `POST /api/v1/data-quality/rules`: Manage custom DQ rules
  - `POST /api/v1/data-quality/apply`: Evaluate rules against existing or incoming tickets
  - `POST /api/v1/data-quality/revert/{run_id}`: Revert flagged tickets from a previous run
- **Monitoring (Phoenix)**: Optional OpenTelemetry API request traces to Arize Phoenix, off by default (`PHOENIX_ENABLED`; see `backend/DEVELOPMENT.md` section 8).

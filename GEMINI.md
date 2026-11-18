# Antigravity & Gemini Agent Instructions & Context Guide

Welcome to the **AMS Agentic Incident Management** project.

> **CRITICAL DIRECTIVE**:
> **DO NOT start reading every source code file across the repository.**
> First read this document and [`AGENTS.md`](AGENTS.md), then read only the target subsystem documentation.

---

## 1. System Overview

This repository hosts an **Application Management Services (AMS) Agentic Incident Management System**:
- **Ticket Ingestion**: Ingests tickets from ServiceNow (`.xlsx`), JIRA, and Support Mailboxes.
- **Three-Tier Agent Pipeline**:
  1. **Data Quality Agent**: Validates ticket completeness, checks for missing data, assigns `dq_flag` & `dq_reason`, and drafts follow-up communications.
  2. **Triage Agent**: Categorizes and normalizes priority against organizational rules.
  3. **Resolution Agent**: Synthesizes resolution instructions by referencing Markdown runbooks in `data/knowledge_base/`.
- **PII Protection**: Integrated Presidio redaction before PostgreSQL database persistence (privacy at rest) and before LLM model invocation.

---

## 2. Fast Documentation Navigator

Read only what is necessary for your task:

| Subsystem | Primary Document | Core Focus |
|---|---|---|
| **Architecture & Layout** | [`AGENTS.md`](AGENTS.md) | High-level system structure, data flow, component layout |
| **Backend / API** | [`backend/DEVELOPMENT.md`](backend/DEVELOPMENT.md) | Pure async FastAPI, SQLAlchemy 2.0 with `asyncpg`, scoped sessions |
| **Database Migrations** | [`backend/db/scripts/DEVELOPMENT.md`](backend/db/scripts/DEVELOPMENT.md) | Numbered idempotent SQL scripts (`01_...`, `02_...`) |
| **Data Quality Pipeline** | [`backend/db/scripts/DQ_RULES_FEATURE.md`](backend/db/scripts/DQ_RULES_FEATURE.md) | 10 operators, first-match-wins, run history & revert tracking |
| **Privacy & Masking** | [`backend/DEVELOPMENT.md`](backend/DEVELOPMENT.md) | Pre-DB Presidio redaction (`caller`, notes, descriptions) |
| **Frontend UI** | [`frontend/DEVELOPMENT.md`](frontend/DEVELOPMENT.md) | Next.js 16 App Router, strict shadcn/ui components |
| **Frontend Rules** | [`frontend/frontend-guidelines.md`](frontend/frontend-guidelines.md) | No raw Tailwind styling for pre-existing primitives |
| **Roadmap & Tasks** | [`TODO.md`](TODO.md) | Current implementation checklist and definition of done |
| **Rules & Guardrails** | [`.agents/rules/karpathy-guidelines.md`](.agents/rules/karpathy-guidelines.md) | Simplicity first, surgical changes, no speculative code |

---

## 3. Strict Operating Guidelines

1. **Simplicity First (Karpathy Guidelines)**:
   - Make minimum surgical changes.
   - Do not refactor untouched code, reformat files, or add unused abstractions.
   - Every modified line must trace directly to the user's prompt.
2. **Database Conventions**:
   - Canonical schemas are in [`backend/db/scripts/`](backend/db/scripts/).
   - Always use `asyncpg` with SQLAlchemy 2.0 async sessions (`Depends(get_db)`).
   - Ingestion and bulk processing must prefetch records via single batch queries (no N+1).
3. **Frontend Component Standards**:
   - Use pre-installed shadcn/ui primitives in `frontend/src/components/ui/` (`Button`, `Card`, `Table`, `Badge`, `Dialog`, `Input`, `Alert`).
   - Run `npm run build` inside `frontend/` to verify zero TypeScript/lint regressions.
4. **Backend Verification**:
   - Run tests and linting before completing:
     ```bash
     ./.venv/bin/pytest backend/tests/
     ./.venv/bin/ruff check backend/
     ```

---

## 4. Current State & Active Endpoints

- **ServiceNow Ingestion**:
  - Endpoint: `POST /api/v1/servicenow/ingest`
  - Accepts: `multipart/form-data` with `file: UploadFile` (.xlsx only, <= 10MB)
  - Target table: `servicenow_tickets` (SQLAlchemy model: `backend/app/models/servicenow.py`)
  - Semantics: Upserts by `ticket_id`, in-file deduplication, header-aware column updating.
  - Privacy: Batch-level Presidio PII masking before DB insert (`caller`, `short_description`, `description`, `resolution_notes`). Controlled via `PII_MASKING_ENABLED`.
- **Data Quality Endpoints**:
  - `POST /api/v1/data-quality/rules` (rule CRUD)
  - `POST /api/v1/data-quality/apply` (evaluate rules against existing or new tickets)
  - `POST /api/v1/data-quality/revert/{run_id}` (revert flag states from previous run)

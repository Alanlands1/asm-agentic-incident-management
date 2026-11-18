# Agent Development References & Guidelines

When working on tasks in this repository, you MUST consult the relevant development guide(s) before proposing or implementing changes. Do NOT inspect every source file across the repository.

1. **System & Architectural Overview**:
   - Primary guide: `AGENTS.md` (or `GEMINI.md` / `CLAUDE.md`)
   - Read this first for project context, ticket pipeline flow, and directory layout.

2. **Backend Development**:
   - Primary guide: `backend/DEVELOPMENT.md`
   - Covers FastAPI conventions, strict async paradigm with `asyncpg`, SQLAlchemy 2.0 on-demand sessions, Supabase integration, and error handling.
   - For ServiceNow ticket ingestion: see `POST /api/v1/servicenow/ingest` in `backend/app/api/v1/endpoints/servicenow.py`.

3. **Database Scripts & Schema Migrations**:
   - Primary guide: `backend/db/scripts/DEVELOPMENT.md`
   - Covers SQL migration ordering and idempotency.
   - For Data Quality (DQ) feature work, consult `backend/db/scripts/DQ_RULES_FEATURE.md` or use the `dq-rules-workflow` skill.

4. **Frontend Development**:
   - Primary guides: `frontend/DEVELOPMENT.md` and `frontend/frontend-guidelines.md`
   - Covers Next.js App Router patterns, mandatory shadcn/ui components (`src/components/ui/`), API client integration, and build verification (`npm run build`).

5. **Privacy & PII Masking**:
   - Primary guides: `backend/DEVELOPMENT.md` and `backend/app/privacy/masking.py`
   - Pre-DB masking using Microsoft Presidio and spaCy NER before persisting tickets to PostgreSQL (`caller`, `short_description`, `description`, `resolution_notes`). Controlled via `PII_MASKING_ENABLED`.

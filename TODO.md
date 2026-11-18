# TODO: Data Quality Rules, Masking & ServiceNow Ingestion

Context: [backend/db/scripts/DQ_RULES_FEATURE.md](backend/db/scripts/DQ_RULES_FEATURE.md), [AGENTS.md](AGENTS.md), and [backend/DEVELOPMENT.md](backend/DEVELOPMENT.md).

| # | Task | Owner | Depends on | Status |
|---|---|---|---|---|
| 1 | Review DB scripts and the DQ rules feature notes | DONE | none | Complete |
| 2 | Create dummy data for the ServiceNow schema, covering the DQ rules | TBD | 1 | Open |
| 3 | Create API endpoints | DONE | 1 | Complete |
| 4 | Add Presidio masking before DB ingestion (`caller`, descriptions, notes) | DONE | 7 | Complete |
| 5 | Update the UI for DQ rule configuration | DONE | 3 | Complete |
| 6 | Add schemas for different ticket sources as well | TBD | none | Open |
| 7 | Synchronize ServiceNow ticket ingestion with DB schema & Excel upload API | DONE | 1, 3 | Complete |
| 8 | Build Frontend UI for ServiceNow Excel Upload & Ingestion | TBD | 7 | Open |
| 9 | Monitoring: API request tracing to Arize Phoenix (OpenTelemetry) | DONE | none | Complete |
| 10 | Monitoring: LLM call tracing via `openinference-instrumentation-anthropic` | DONE | 9 | Complete |

## 1. Review DB scripts and feature notes
- Review [01_create_servicenow_tickets.sql](db/scripts/01_create_servicenow_tickets.sql) and [02_create_dq_rules.sql](db/scripts/02_create_dq_rules.sql). Run them on a dev database to verify.
- Answer the open questions in `DQ_RULES_FEATURE.md` (revert order, per-source fields, rule edit history, `dq_reason` with several matches).
- Done when: scripts approved, or follow-up scripts (`03_...`) agreed.

## 2. Dummy data
- Rows in the AMS team's ServiceNow schema, as a SQL script in `db/scripts/` (e.g. `03_seed_servicenow_tickets.sql`).
- Cover each operator and `apply_to` case: short or empty descriptions, `test` tickets, blank fields, unresolved (`closed_at` NULL) and closed tickets, several services and priorities (e.g. `4 - Low`).
- Include a few sample `dq_rules` and tickets that should and should not match.
- Done when: applying the sample rules gives a known, documented set of flagged tickets.

## 3. API endpoints
- Needs the models and services updated first (`app/models/ticket.py` still defines the old tables).
- Rules: create, list, get, edit, toggle enabled, soft delete.
- Apply: run on existing, new or both; list runs; show a run's matches; revert a run.
- Tickets: list with the DQ flag and reason, filterable.
- Follow the async conventions in [DEVELOPMENT.md](DEVELOPMENT.md).
- Done when: endpoints are covered by tests against the dummy data.

## 4. Presidio masking before DB ingestion
- Mask `caller`, `short_description`, `description`, and `resolution_notes` before records are stored in PostgreSQL (`servicenow_tickets` and other sources).
- Implemented inline execution via Microsoft Presidio + spaCy NER (`Masker`), with batch-level known caller mapping and entity leak verification.
- Adheres to approved Option A: Irreversible anonymized placeholders (`<PERSON_n>`, `<EMAIL_n>`, `<PHONE_n>`, `<EMPLOYEE_ID_n>`) at rest in PostgreSQL, with upstream `ticket_id` link.
- System accounts (`Service Desk`, `Integration User`) and enterprise application/error entities are strictly preserved.
- Added toggle `PII_MASKING_ENABLED` in `app/core/config.py`.
- Verified with 5 dedicated tests in `backend/tests/test_ingestion_masking.py` and 15 tests in `backend/tests/test_servicenow_api.py`.
- Done when: no caller name, personal phone, or email survives in stored ticket records, verified on sample ticket sets. (Complete)

## 5. UI for rule configuration
- Rule list with enable toggle, create, edit and delete.
- Choose field, operator, value, source or service, and when to apply (existing, new, both).
- Apply button, run history, and revert.
- Done when: all of the above work against the API from item 3.

## 7. Synchronize ServiceNow ticket ingestion with DB schema & Excel upload API
- Aligned `ServiceNowTicket` ORM model, schema, and `ingest_servicenow_file` with canonical `servicenow_tickets` table (`01_create_servicenow_tickets.sql`).
- Added dedicated `POST /api/v1/servicenow/ingest` upload endpoint with `.xlsx` restriction and 10MB payload limit.
- Hardened service with single batch query prefetch (eliminating N+1), in-file duplicate deduplication, header-aware partial updates, and corrupt file safety.
- Covered by 15 tests in `backend/tests/test_servicenow_api.py`.

## 8. Frontend UI for ServiceNow Excel Upload & Ingestion
- Add `ingestServiceNowTickets(file: File)` to `frontend/src/lib/api.ts`.
- Build ServiceNow ticket upload component (file input or drag-and-drop using shadcn/ui).
- Render upload results summary (processed, created, updated, skipped counts).
- Verify with `npm run build` in `frontend/`.

## 10. LLM call tracing via `openinference-instrumentation-anthropic`
- Add LLM call spans (prompts, model, tokens, latency) on top of the API request traces from item 9, sent to the same Phoenix project.
- Keep PII out of spans: confirm what is attached before enabling, since prompts contain ticket text (already masked by `Masker`).
- Done when: a resolution or DQ model call shows as a span in Phoenix, and tracing stays off unless `PHOENIX_ENABLED=true`.

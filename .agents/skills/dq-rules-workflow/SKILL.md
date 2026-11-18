---
name: dq-rules-workflow
description: >-
  Use this skill when developing, authoring, modifying, testing, or executing database scripts,
  schemas, or backend logic related to Data Quality (DQ) Rules, servicenow_tickets, dq_rules,
  dq_runs, or dq_run_tickets.
---

# Data Quality (DQ) Rules Workflow

This skill guides the design, implementation, and execution of Data Quality (DQ) filtering rules on incoming and existing tickets.

---

## 1. Core Reference Documentation
- Consult [`references/DQ_RULES_FEATURE.md`](./references/DQ_RULES_FEATURE.md) for complete requirements, table schemas, operators, revert logic, and confirmed design decisions.

---

## 2. Database Scripts Conventions
When creating or updating SQL scripts in `backend/db/scripts/`:
1. **Script Ordering**: Ensure migrations follow sequential numbering (e.g. `01_create_servicenow_tickets.sql`, `02_create_dq_rules.sql`).
2. **Idempotency**: All DDL must be safe to re-run (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).
3. **Execution Order**:
   - `01_create_servicenow_tickets.sql` must run before `02_create_dq_rules.sql` because `dq_run_tickets` references `servicenow_tickets`.

---

## 3. Key Feature Rules & Assumptions
- **First match wins**: Rules evaluate in `id` order. When a ticket matches, `dq_flag = true` and `dq_reason = <rule_name>`, then evaluation stops for that ticket.
- **Rule Scope**: Rules can be global or bounded to a `source` or `service`.
- **Soft Deletes**: Rules use soft delete via `deleted_at`.
- **Apply Scopes**:
  - `existing`: Unresolved tickets (`closed_at IS NULL`).
  - `new`: Incoming ingestion stream.
  - `both`: Both existing unresolved and future tickets.
- **Run Tracking & Revert**: Every apply run records an entry in `dq_runs` and flagged tickets in `dq_run_tickets` to allow reverting flag states.

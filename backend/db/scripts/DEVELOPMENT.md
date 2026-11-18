# Database Scripts & Migrations Development Guide

This document outlines conventions and instructions for modifying and authoring database scripts in `backend/db/scripts/`.

---

## 1. Script Conventions & Workflow

- **Execution Environment**: Plain PostgreSQL / Supabase SQL run via workbench (Supabase SQL Editor, DBeaver, pgAdmin) or migration runner.
- **Ordering**: Numbered sequentially (`01_...`, `02_...`). Always execute scripts in ascending numeric order.
- **Idempotency**: All DDL statements should be idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS`).

---

## 2. Feature Documentation References

- **Data Quality Rules Feature**:
  - Reference: [`DQ_RULES_FEATURE.md`]
  - Details the design, schema requirements, and assumptions for data quality filtering on tickets (`servicenow_tickets`, `dq_rules`, `dq_runs`, `dq_run_tickets`).
  - Consult this document whenever authoring or modifying data quality table definitions, rule evaluation logic, or migration scripts touching the DQ pipeline.

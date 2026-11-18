# Data Quality Rules: feature notes

Scripts: [01_create_servicenow_tickets.sql](01_create_servicenow_tickets.sql), [02_create_dq_rules.sql](02_create_dq_rules.sql)

## Requirements (as discussed)

- ServiceNow is the only source for now. Jira and Mail come later, with their own schemas.
- Ticket schema is the one the AMS team supplied: ticket id, caller, short description, description, priority, assignment group, service, resolution notes, opened datetime, closed datetime.
- Tickets are masked first, then stored, then filtered by data quality rules. Filtered tickets stay in the DB with a flag. Masking is not part of these scripts.
- Users can create, edit, delete and toggle (enable/disable) rules.
- A rule is structured: a field, an operator and a value (e.g. `description length_lt 50`, `short_description contains 'test'`).
- When a rule matches, the ticket is flagged and the rule name is stored as the reason.
- Rules are checked in order and the first match wins. Which rule flagged which ticket is stored per run.
- A rule can be applied to existing unresolved tickets, to upcoming tickets, or both. This is configurable.
- Rules can be global or bound to a source or a service.
- Every apply is kept as history so it can be reverted.
- Deleting a rule is a soft delete (`deleted_at`).

## Implementation

| Table | Purpose |
|---|---|
| `servicenow_tickets` | Tickets plus `dq_flag` (default false) and `dq_reason`. `priority` is text, e.g. `4 - Low`. |
| `dq_rules` | The rules: `field`, `operator`, `value`, `source`, `service`, `apply_to`, `is_enabled`, `deleted_at`. |
| `dq_runs` | One row per apply: trigger (`manual`/`ingestion`), scope, rules snapshot, counts, status (`running`/`completed`/`failed`/`reverted`). |
| `dq_run_tickets` | Per ticket flagged by a run: the `rule_id` that matched, and `reverted_dq_flag` / `reverted_dq_reason`, the values restored if the run is reverted. |

Details:
- Operators: `equals`, `not_equals`, `contains`, `not_contains`, `starts_with`, `regex`, `is_empty`, `is_not_empty`, `length_lt`, `length_gt`.
- `source` or `service` NULL means the rule is global or applies to any service.
- `apply_to`: `existing` (stored tickets with `closed_at IS NULL`), `new` (incoming tickets), `both`.
- Rule names are unique among non-deleted rules (case-insensitive).
- First match wins: rules are evaluated in `id` order and a ticket stops at its first matching rule. `dq_reason` holds that one rule name.
- Not yet run against a database. Needs `01` before `02`.

## Assumptions

- A match sets `dq_flag = true` and `dq_reason = <rule name>`. There is no per-rule outcome such as `needs_info`.
- "Unresolved" means `closed_at IS NULL`.
- Revert restores the `reverted_dq_flag` / `reverted_dq_reason` saved in `dq_run_tickets` for that run. It does not replay older rule states.
- `field` is free text naming a ticket column; the app validates it.
- No generic audit table for rule edits. Only apply runs are recorded.
- The old generic `tickets` and `agent_runs` tables are no longer in the scripts. `app/models/ticket.py` still defines them and needs updating separately.

## To confirm

1. Should reverting an older run be blocked while a newer run touched the same ticket? (App logic, not a table change.)
2. When Jira and Mail tables arrive, should rules read each source's own columns, or a common set of fields?
3. Should a rule's edit history be kept (the runs only store a rules snapshot)?

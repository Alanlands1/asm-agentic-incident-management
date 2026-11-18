-- Data quality rules, apply runs and the tickets each run flagged (PostgreSQL / Supabase). Safe to re-run.
-- Run after 01_create_servicenow_tickets.sql.

-- Ticket source lookup reference table
CREATE TABLE IF NOT EXISTS ticket_sources (
    code VARCHAR(32) PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed standard enterprise ticket source systems
INSERT INTO ticket_sources (code, name, description)
VALUES 
    ('servicenow', 'ServiceNow', 'Enterprise ServiceNow IT Service Management incident feed'),
    ('jira', 'Jira', 'Atlassian Jira Service Management / Software issue feed'),
    ('mailbox', 'Support Mailbox', 'Inbound support email mailbox and shared distribution list')
ON CONFLICT (code) DO NOTHING;

-- A rule: "<field> <operator> <value>" -> flags the ticket (dq_flag = true, dq_reason = rule name).
CREATE TABLE IF NOT EXISTS dq_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    field VARCHAR(64) NOT NULL,          -- ticket column, e.g. description, short_description, priority
    operator VARCHAR(32) NOT NULL CHECK (operator IN (
        'equals', 'not_equals', 'contains', 'not_contains', 'starts_with',
        'regex', 'is_empty', 'is_not_empty', 'length_lt', 'length_gt')),
    value TEXT,                          -- NULL for is_empty / is_not_empty
    source VARCHAR(32) REFERENCES ticket_sources(code) ON DELETE SET NULL, -- NULL = global (any source)
    service VARCHAR(64),                 -- NULL = any service
    apply_to VARCHAR(16) NOT NULL DEFAULT 'both' CHECK (apply_to IN ('existing', 'new', 'both')),
                                         -- existing = stored unresolved tickets (closed_at IS NULL), new = incoming tickets
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,   -- the user toggle
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ               -- soft delete
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dq_rules_name_active ON dq_rules (lower(name)) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_dq_rules_enabled ON dq_rules (is_enabled) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_dq_rules_source ON dq_rules (source);

-- One row per apply: history of runs.
CREATE TABLE IF NOT EXISTS dq_runs (
    id SERIAL PRIMARY KEY,
    trigger VARCHAR(16) NOT NULL CHECK (trigger IN ('manual', 'ingestion')),
    scope VARCHAR(16) NOT NULL CHECK (scope IN ('existing', 'new', 'both')),
    rules_snapshot JSONB NOT NULL DEFAULT '[]',   -- rules as they were when applied
    tickets_evaluated INTEGER NOT NULL DEFAULT 0,
    tickets_flagged INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'reverted')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    reverted_at TIMESTAMPTZ
);

-- Per ticket flagged by a run (first matching rule wins, in id order).
-- rule_id = the rule that matched; reverted_* = the values restored on the ticket if the run is reverted.
CREATE TABLE IF NOT EXISTS dq_run_tickets (
    run_id INTEGER NOT NULL REFERENCES dq_runs (id) ON DELETE CASCADE,
    ticket_id VARCHAR(32) NOT NULL REFERENCES servicenow_tickets (ticket_id) ON DELETE CASCADE,
    rule_id INTEGER NOT NULL REFERENCES dq_rules (id),
    reverted_dq_flag BOOLEAN NOT NULL,
    reverted_dq_reason VARCHAR(256),
    PRIMARY KEY (run_id, ticket_id)
);
CREATE INDEX IF NOT EXISTS ix_dq_run_tickets_ticket ON dq_run_tickets (ticket_id);
CREATE INDEX IF NOT EXISTS ix_dq_run_tickets_rule ON dq_run_tickets (rule_id);

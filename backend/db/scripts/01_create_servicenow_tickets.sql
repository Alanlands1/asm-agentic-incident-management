-- ServiceNow tickets (PostgreSQL / Supabase). Safe to re-run.
-- Columns follow the schema supplied by the AMS team. Jira and Mailbox get their own tables later.
CREATE TABLE IF NOT EXISTS servicenow_tickets (
    ticket_id VARCHAR(32) PRIMARY KEY,   -- e.g. INC0010231
    caller VARCHAR(128),
    short_description VARCHAR(512),
    description TEXT,
    priority VARCHAR(32),                -- as in the source, e.g. '4 - Low'
    assignment_group VARCHAR(64),
    service VARCHAR(64),
    resolution_notes TEXT,
    opened_at TIMESTAMP,
    closed_at TIMESTAMP,

    -- data quality: the ticket is always stored; the flag marks it as filtered out
    dq_flag BOOLEAN NOT NULL DEFAULT FALSE,
    dq_reason VARCHAR(256),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_servicenow_tickets_service ON servicenow_tickets (service);
CREATE INDEX IF NOT EXISTS ix_servicenow_tickets_opened_at ON servicenow_tickets (opened_at);
CREATE INDEX IF NOT EXISTS ix_servicenow_tickets_dq_flag ON servicenow_tickets (dq_flag);

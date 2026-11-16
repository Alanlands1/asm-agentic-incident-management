-- A person's note to the agents on a ticket (tickets.guidance) and their star rating of an agent's result (agent_feedback).
-- Safe to re-run. Run after 09_add_review_final_text.sql.

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS guidance TEXT;

CREATE TABLE IF NOT EXISTS agent_feedback (
    id            SERIAL PRIMARY KEY,
    ticket_id     VARCHAR(32)  NOT NULL REFERENCES tickets (id) ON DELETE CASCADE,
    agent_run_id  INTEGER      NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    agent         VARCHAR(32)  NOT NULL,              -- data_quality, triage, resolution, closure_quality
    stars         INTEGER      NOT NULL CHECK (stars BETWEEN 1 AND 5),
    reason        TEXT         NOT NULL,              -- why this many stars
    reviewer      VARCHAR(256) NOT NULL,              -- as given by the console, not verified until there are logins
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_feedback_ticket_id ON agent_feedback (ticket_id);
CREATE INDEX IF NOT EXISTS ix_agent_feedback_agent_run_id ON agent_feedback (agent_run_id);
CREATE INDEX IF NOT EXISTS ix_agent_feedback_agent ON agent_feedback (agent);

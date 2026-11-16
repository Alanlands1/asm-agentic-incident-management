-- Jira pull: the projects an admin picked, and the history of every sync.
CREATE TABLE IF NOT EXISTS jira_projects (
    key         VARCHAR(32)  PRIMARY KEY,       -- Jira project key, e.g. AMS
    name        VARCHAR(128) NOT NULL,
    team        VARCHAR(64),                    -- stored as assignment_group on pulled tickets, null = project name
    selected_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jira_syncs (
    id          SERIAL PRIMARY KEY,
    trigger     VARCHAR(16)  NOT NULL,          -- manual | schedule
    projects    VARCHAR(512) NOT NULL DEFAULT '',
    started_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    pulled      INTEGER      NOT NULL DEFAULT 0,
    created     INTEGER      NOT NULL DEFAULT 0,
    updated     INTEGER      NOT NULL DEFAULT 0,
    queued      INTEGER      NOT NULL DEFAULT 0,    -- new open tickets handed to the agents
    error       TEXT                            -- null = succeeded
);
CREATE INDEX IF NOT EXISTS ix_jira_syncs_started_at ON jira_syncs (started_at DESC);
ALTER TABLE jira_syncs ADD COLUMN IF NOT EXISTS queued INTEGER NOT NULL DEFAULT 0;

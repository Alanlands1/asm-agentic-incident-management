-- Knowledge Builder (app/models/knowledge.py): drafted articles, saved cases (all text masked) and repeat-issue suggestions.
-- Safe to re-run. Run after 10_add_guidance_feedback.sql.

CREATE TABLE IF NOT EXISTS kb_drafts (
    id                SERIAL PRIMARY KEY,
    application       VARCHAR(64)  NOT NULL,
    kb_id             VARCHAR(32)  UNIQUE,               -- given on approval, e.g. KB-PAY-006
    title             VARCHAR(256) NOT NULL,
    symptoms          JSON         NOT NULL DEFAULT '[]',
    root_cause        TEXT         NOT NULL,
    resolution_steps  JSON         NOT NULL DEFAULT '[]',
    escalation        TEXT         NOT NULL,
    source_ticket_ids JSON         NOT NULL DEFAULT '[]',
    status            VARCHAR(16)  NOT NULL DEFAULT 'draft',  -- draft | approved | rejected
    reviewer          VARCHAR(256),                     -- as given by the caller, not verified until there are logins
    reason_code       VARCHAR(32),
    note              TEXT,
    decided_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_kb_drafts_application ON kb_drafts (application);
CREATE INDEX IF NOT EXISTS ix_kb_drafts_status ON kb_drafts (status);

CREATE TABLE IF NOT EXISTS resolved_cases (
    ticket_id     VARCHAR(32)  PRIMARY KEY REFERENCES tickets (id) ON DELETE CASCADE,
    application   VARCHAR(64),
    summary       VARCHAR(512) NOT NULL,
    description   TEXT         NOT NULL,
    notes         TEXT         NOT NULL,                -- the final close notes: the engineer's edit if there was one
    cause         TEXT,                                 -- the words that showed the cause, action and check
    action        TEXT,
    "check"       TEXT,
    score         INTEGER,                              -- Closure Quality, out of 6
    match_status  VARCHAR(16)  NOT NULL,                -- matched | gap | uncertain
    kb_article_id VARCHAR(32),
    match_method  VARCHAR(16),                          -- cited | code | keywords | model
    gap_kind      VARCHAR(16),                          -- for a gap: known_issue | request | outside_kb
    draft_id      INTEGER      REFERENCES kb_drafts (id) ON DELETE SET NULL,
    closed_at     TIMESTAMP,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_resolved_cases_application ON resolved_cases (application);
CREATE INDEX IF NOT EXISTS ix_resolved_cases_match_status ON resolved_cases (match_status);
CREATE INDEX IF NOT EXISTS ix_resolved_cases_kb_article_id ON resolved_cases (kb_article_id);
CREATE INDEX IF NOT EXISTS ix_resolved_cases_draft_id ON resolved_cases (draft_id);

CREATE TABLE IF NOT EXISTS problem_candidates (
    id           SERIAL PRIMARY KEY,
    application  VARCHAR(64),
    issue_key    VARCHAR(64)  NOT NULL,                 -- article:KB-PAY-002 or draft:12
    ticket_ids   JSON         NOT NULL DEFAULT '[]',
    cases        INTEGER      NOT NULL,
    first_closed TIMESTAMP    NOT NULL,
    last_closed  TIMESTAMP    NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'open',  -- open | accepted | dismissed
    decided_by   VARCHAR(256),
    decided_at   TIMESTAMPTZ,
    note         TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_problem_candidates_application ON problem_candidates (application);
CREATE INDEX IF NOT EXISTS ix_problem_candidates_issue_key ON problem_candidates (issue_key);
CREATE INDEX IF NOT EXISTS ix_problem_candidates_status ON problem_candidates (status);

-- Triage storms (app/models/ticket.py Storm) and the link from each ticket to its storm.
-- For databases whose tickets table was created before storms existed.
CREATE TABLE IF NOT EXISTS storms (
    id              SERIAL       PRIMARY KEY,
    application     VARCHAR(64),
    issue_key       VARCHAR(128) NOT NULL,
    main_ticket_id  VARCHAR(32)  NOT NULL,
    people          INTEGER      NOT NULL,
    ticket_count    INTEGER      NOT NULL,
    opened_at       TIMESTAMP    NOT NULL,
    last_ticket_at  TIMESTAMP    NOT NULL,
    status          VARCHAR(16)  NOT NULL,
    declared_by     VARCHAR(256),
    declared_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_storms_status ON storms (status);
CREATE INDEX IF NOT EXISTS ix_storms_application ON storms (application);
CREATE INDEX IF NOT EXISTS ix_storms_main_ticket_id ON storms (main_ticket_id);

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS storm_id INTEGER REFERENCES storms (id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_tickets_storm_id ON tickets (storm_id);

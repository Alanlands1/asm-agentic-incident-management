-- First messages for P1/P2 tickets that a person marked as sent (the text as sent, who, when).
CREATE TABLE IF NOT EXISTS first_messages (
    id          SERIAL PRIMARY KEY,
    ticket_id   VARCHAR(32)  NOT NULL REFERENCES tickets (id) ON DELETE CASCADE,
    storm_id    INTEGER      REFERENCES storms (id) ON DELETE SET NULL,
    text        TEXT         NOT NULL,
    sent_by     VARCHAR(256) NOT NULL,              -- as given by the console, not verified until there are logins
    sent_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_first_messages_ticket_id ON first_messages (ticket_id);

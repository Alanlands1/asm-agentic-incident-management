-- Sign-in (app/models/user.py): the people who may open the console, and their open sessions.
-- Safe to re-run. Run after 11_create_knowledge.sql. Add people with backend/scripts/create_user.py.

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(256) NOT NULL UNIQUE,     -- what they sign in with, stored in lower case
    name          VARCHAR(128) NOT NULL,            -- as in Jira: tickets.assignee holds this name
    role          VARCHAR(16)  NOT NULL,            -- admin | lead | engineer
    password_hash VARCHAR(256) NOT NULL,            -- scrypt$<salt hex>$<hash hex>; never the password
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash  VARCHAR(64)  PRIMARY KEY,           -- SHA-256 of the cookie's value; the value itself is not stored
    user_id     INTEGER      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions (user_id);

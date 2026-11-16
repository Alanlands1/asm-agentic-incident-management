-- Confluence copy: the spaces an admin picked, every page in them as plain text, and the history of every sync.
CREATE TABLE IF NOT EXISTS confluence_spaces (
    key         VARCHAR(255) PRIMARY KEY,       -- Confluence space key, e.g. AMSKB
    space_id    VARCHAR(32)  NOT NULL,
    name        VARCHAR(255) NOT NULL,
    selected_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS confluence_pages (
    id          VARCHAR(32)  PRIMARY KEY,       -- Confluence page id
    space_key   VARCHAR(255) NOT NULL,
    title       VARCHAR(255) NOT NULL,
    version     INTEGER      NOT NULL,
    body        TEXT         NOT NULL DEFAULT '', -- page content as plain text with markdown-style headings, lists and tables
    url         VARCHAR(1024),
    synced_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_confluence_pages_space_key ON confluence_pages (space_key);

CREATE TABLE IF NOT EXISTS confluence_syncs (
    id          SERIAL PRIMARY KEY,
    trigger     VARCHAR(16)  NOT NULL,          -- manual | schedule
    spaces      VARCHAR(512) NOT NULL DEFAULT '',
    started_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    pulled      INTEGER      NOT NULL DEFAULT 0,
    created     INTEGER      NOT NULL DEFAULT 0,
    updated     INTEGER      NOT NULL DEFAULT 0,
    removed     INTEGER      NOT NULL DEFAULT 0,    -- pages deleted in Confluence since the last sync
    error       TEXT
);
CREATE INDEX IF NOT EXISTS ix_confluence_syncs_started_at ON confluence_syncs (started_at DESC);

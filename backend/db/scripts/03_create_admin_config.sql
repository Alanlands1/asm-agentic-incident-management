-- Admin API: current overrides of settings / reference documents, and the history of every change.
CREATE TABLE IF NOT EXISTS config_overrides (
    kind        VARCHAR(16)  NOT NULL,          -- setting | document
    key         VARCHAR(64)  NOT NULL,          -- e.g. LLM_MODEL, prompts
    value       JSON,
    claimed_by  VARCHAR(128) NOT NULL,          -- from X-Admin-User; not verified
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS config_changes (
    id          SERIAL PRIMARY KEY,
    kind        VARCHAR(16)  NOT NULL,
    key         VARCHAR(64)  NOT NULL,
    old_value   JSON,
    new_value   JSON,                           -- null when the override was removed
    claimed_by  VARCHAR(128) NOT NULL,
    changed_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_config_changes_kind ON config_changes (kind);
CREATE INDEX IF NOT EXISTS ix_config_changes_key  ON config_changes (key);

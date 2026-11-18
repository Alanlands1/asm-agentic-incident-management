-- Resolution agent: knowledge base chunks with contextual text, metadata, embedding and full-text index (PostgreSQL / Supabase).
-- Safe to re-run. Run after 03_create_admin_config.sql.
-- The embedding column stays NULL until embeddings are generated (outside the app); its size must match EMBEDDING_DIM.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_chunks (
    id                 BIGSERIAL PRIMARY KEY,
    source_path        VARCHAR(255) NOT NULL,       -- e.g. payrollpro.md
    chunk_index        INTEGER      NOT NULL,       -- order within the file
    app                VARCHAR(128) NOT NULL,       -- application name as in apps.yaml, e.g. PayrollPro
    app_id             VARCHAR(32),                 -- e.g. APP-PAY
    kb_id              VARCHAR(32),                 -- e.g. KB-PAY-001; NULL for overview and escalation sections
    section_type       VARCHAR(16)  NOT NULL,       -- header | overview | issue | escalation
    title              TEXT         NOT NULL,       -- the heading of the chunk, e.g. "Payslip PDF is blank..."
    heading_path       TEXT         NOT NULL,       -- "PayrollPro > Known issues and resolutions > KB-PAY-001 ..."
    support_group      VARCHAR(128),
    criticality_tier   VARCHAR(16),                 -- e.g. Tier 1
    authority          VARCHAR(16)  NOT NULL DEFAULT 'primary',  -- primary = official KB; ticket history comes later
    content            TEXT         NOT NULL,       -- the chunk as written in the runbook
    context            TEXT         NOT NULL DEFAULT '',  -- contextual retrieval blurb, prepended for search
    content_hash       VARCHAR(64)  NOT NULL,       -- sha256 of content; unchanged chunks are not re-processed
    embedding          vector(256),                 -- NULL until generated
    embedding_model    VARCHAR(128),
    fts                tsvector GENERATED ALWAYS AS (
                           to_tsvector('english', coalesce(context, '') || ' ' || coalesce(title, '') || ' ' || content)
                       ) STORED,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_kb_chunks_source_index UNIQUE (source_path, chunk_index)
);

CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding ON kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_fts ON kb_chunks USING gin (fts);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_app ON kb_chunks (app);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_kb_id ON kb_chunks (kb_id);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_criticality ON kb_chunks (criticality_tier);

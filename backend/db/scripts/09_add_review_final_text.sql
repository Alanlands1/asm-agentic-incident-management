-- Closure Quality: the notes the engineer settled on when editing the agent's close note (Review.final_text).
-- Safe to re-run. Run after 06_add_triage_storms.sql.

ALTER TABLE agent_reviews ADD COLUMN IF NOT EXISTS final_text TEXT;

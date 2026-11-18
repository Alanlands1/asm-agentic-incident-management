-- DESTRUCTIVE: removes all ticket and data quality data. Dev/test only.
DROP TABLE IF EXISTS agent_feedback;
DROP TABLE IF EXISTS first_messages;
DROP TABLE IF EXISTS confluence_syncs;
DROP TABLE IF EXISTS confluence_pages;
DROP TABLE IF EXISTS confluence_spaces;
DROP TABLE IF EXISTS storms CASCADE;
DROP TABLE IF EXISTS jira_syncs;
DROP TABLE IF EXISTS jira_projects;
DROP TABLE IF EXISTS kb_chunks;
DROP TABLE IF EXISTS config_changes;
DROP TABLE IF EXISTS config_overrides;
DROP TABLE IF EXISTS dq_run_tickets;
DROP TABLE IF EXISTS dq_runs;
DROP TABLE IF EXISTS dq_rules;
DROP TABLE IF EXISTS ticket_sources;
DROP TABLE IF EXISTS servicenow_tickets;

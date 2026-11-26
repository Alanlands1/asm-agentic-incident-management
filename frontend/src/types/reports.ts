/** Admin reports for a period (backend/app/api/v1/endpoints/dashboard.py, ReportsOut). Shares are 0..1, null when there is nothing to measure. */

export interface ApplicationReport {
  application: string;
  opened: number;
  open: number;
  resolved: number;
  p1_p2: number;
  sla_met: number | null;
  mean_hours_to_resolve: number | null;
  runbook_fix: number | null;
  kb_covered: number | null;
}

export interface AgentReport {
  agent: string;
  runs: number;
  model_used: number | null;
  model_failed: number;
  tokens: number;
  rated: number;
  correct: number | null;
  partially_correct: number | null;
  incorrect: number | null;
}

export interface OutcomeReport {
  application: string;
  fixes_confirmed: number;
  first_fix: number | null;
  mean_attempts: number | null;
  escalated: number;
  mean_closure_score: number | null;
  closure_needs_work: number | null;
  lead_approved: number;
  lead_returned: number;
}

export interface EngineerReport {
  engineer: string;
  open: number;
  closed: number;
  mean_hours_to_resolve: number | null;
  sla_breached: number;
  priority_changes: number;
}

export interface Reports {
  days: number;
  since: string;
  applications: ApplicationReport[];
  agents: AgentReport[];
  outcomes: OutcomeReport[];
  engineers: EngineerReport[];
}

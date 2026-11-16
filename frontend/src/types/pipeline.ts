/** One agent's verdict on a ticket. `output` is the agent's own record: stage, rule, reason, signals, model audit. */
export interface AgentRun {
  id: number;
  agent: string;
  verdict: string;
  output: Record<string, unknown>;
  created_at: string;
}

export interface TicketComment {
  id: number;
  author_email: string;
  from_reporter: boolean;
  body: string;
  created_at: string;
}

/** A person's star rating of one agent result, with the reason they gave. */
export interface AgentFeedback {
  id: number;
  agent_run_id: number;
  agent: string;
  stars: number;
  reason: string;
  reviewer: string;
  created_at: string;
}

export interface PipelineTicket {
  id: string;
  source: string;
  reporter_name: string | null;
  application: string | null;
  summary: string;
  reported_priority: number | null;
  reported_priority_label: string | null;
  status: string;
  source_status: string | null;
  pipeline_status: string;
  opened_at: string | null;
  closed_at: string | null;
  description: string;
  assignment_group: string | null;
  assignee: string | null;
  agent_runs: AgentRun[];
  comments: TicketComment[];
  /** A person's note to the agents, read with the description on every run. */
  guidance: string | null;
  /** Oldest first. Missing from a backend that has not been restarted since ratings were added. */
  feedback?: AgentFeedback[];
  /** The last decision a person made on the priority, in the console or on the Jira issue. */
  decided: { final_priority: number | null; reviewer: string; note: string | null } | null;
}

export interface ReviewQueueItem {
  ticket_id: string;
  summary: string;
  application: string | null;
  opened_at: string | null;
  reported_priority: number | null;
  recommended_priority: number;
  rule: string | null;
  reason: string;
  stage: string;
  flags: string[];
}

export const REASON_CODES = [
  { value: "wrong_facts", label: "The facts are wrong" },
  { value: "wrong_rule", label: "The wrong rule fired" },
  { value: "wrong_application", label: "Wrong application" },
  { value: "no_rule_fits", label: "No rule fits" },
  { value: "other", label: "Other" },
] as const;

export interface ReviewInput {
  action: "accepted" | "edited" | "rejected";
  reviewer: string;
  priority?: number;
  reason_code?: (typeof REASON_CODES)[number]["value"];
  note?: string;
}

export interface AgentRunResult {
  evaluated: number;
  skipped: number;
  model_errors: number;
  needs_review?: number;
  by_verdict: Record<string, number>;
}

export interface AgentCheckResult {
  ticket_id: string;
  verdict: string;
  stage: string;
  pipeline_status?: string;
  output: Record<string, unknown>;
}

export type AgentSlug = "data-quality" | "triage" | "resolution" | "closure";

/** Close notes that need work: what to ask the engineer, and a draft built only from what is on the ticket. */
export interface ClosureQueueItem {
  ticket_id: string;
  summary: string;
  application: string | null;
  notes: string | null;
  score: number | null;
  reason: string;
  questions: string[];
  draft_notes: string | null;
}

/** Why a recommendation needs a closer look. */
export const FLAGS: Record<string, string> = {
  downgrade: "Lower than the reporter asked",
  leaned_high: "Leaned high: facts missing",
  kept_reported: "Kept the reporter's priority",
  large_shift: "Far from the reporter's priority",
};

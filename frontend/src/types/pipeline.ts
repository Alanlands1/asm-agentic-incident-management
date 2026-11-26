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
  reporter_email?: string | null;
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
  /** The close notes as they are in the source. */
  resolution_notes?: string | null;
  agent_runs: AgentRun[];
  comments: TicketComment[];
  /** A person's note to the agents, read with the description on every run. */
  guidance: string | null;
  /** Oldest first. Missing from a backend that has not been restarted since ratings were added. */
  feedback?: AgentFeedback[];
  /** The last decision a person made on the priority, in the console or on the Jira issue. */
  decided: { final_priority: number | null; reviewer: string; note: string | null; created_at: string } | null;
  /** The last decision a person made on the close notes. Missing from an older backend. */
  closure_decision?: { agent_run_id: number; action: "accepted" | "edited" | "rejected"; final_text: string | null; note: string | null } | null;
  /** Per agent that ran before: true when its input changed since its last run. Missing from an older backend. */
  changed?: Partial<Record<string, boolean>>;
  /** True while the agents' pass after a Jira sync is running. Missing from an older backend. */
  agents_running?: boolean;
  /** The engineer's answers on the suggested fixes, oldest first; the latest on a fix counts. */
  fix_outcomes?: FixOutcome[];
  /** A lead approves the closure note before it is sent (LEAD_REVIEW). Missing from an older backend. */
  lead_review_required?: boolean;
  /** Submitted for review, approved, sent back (with the comment), oldest first. */
  lead_reviews?: LeadReviewStep[];
}

/** A row of the ticket list (GET /tickets). */
export interface TicketListItem {
  id: string;
  source: string;
  application: string | null;
  summary: string;
  reported_priority: number | null;
  pipeline_status: string;
  opened_at: string | null;
}

export interface LeadReviewStep {
  action: "submitted" | "approved" | "sent_back";
  note: string | null;
  reviewer: string;
  created_at: string;
}

export type Outcome = "worked" | "partly" | "wrong";

export interface FixOutcome {
  agent_run_id: number;
  action: Outcome;
  note: string | null;
  reviewer: string;
  created_at: string;
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
  { value: "wrong_facts", label: "Incorrect facts" },
  { value: "wrong_rule", label: "Wrong rule applied" },
  { value: "wrong_application", label: "Wrong application" },
  { value: "no_rule_fits", label: "No applicable rule" },
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
  downgrade: "Lower than requested",
  leaned_high: "Set high: facts missing",
  kept_reported: "Requested priority kept",
  large_shift: "Large change from requested priority",
};

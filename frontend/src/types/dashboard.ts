export interface AgentStats {
  checked: number;
  by_verdict: Record<string, number>;
  model_used: number;
  model_failed: number;
}

export interface SyncHealth {
  state: "off" | "never" | "running" | "stale";
  minutes: number;
  last_started_at: string | null;
  last_error: string | null;
  last_summary: string | null;
}

export interface DashboardSummary {
  tickets: { by_source_today: Record<string, number>; by_stage: Record<string, number> };
  agents: { data_quality: AgentStats; triage: AgentStats };
  review_queue: { size: number; oldest_at: string | null; p1_p2: number };
  agreement: { days: number; reviewed: number; agreement: number };
  syncs: { jira: SyncHealth; confluence: SyncHealth };
  attention: number;
}

export interface Trends {
  /** The start of each day. Every list below has one number per day. */
  days: string[];
  tickets: Record<string, number[]>;
  tokens: Record<string, number[]>;
  tokens_in: number;
  tokens_out: number;
  model_calls: number;
  sla_breaches: Record<string, number[]>;
  sla_open: { breached: number; breach_likely: number };
  reviews: Record<string, number>;
}

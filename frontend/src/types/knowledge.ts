/** Knowledge Builder: drafted articles for gaps, repeat issues and coverage (backend/app/schemas/knowledge.py). */

export type DraftStatus = "draft" | "approved" | "rejected";

export interface KBDraft {
  id: number;
  application: string;
  kb_id: string | null; // given on approval, e.g. KB-PAY-006
  title: string;
  symptoms: string[];
  root_cause: string;
  resolution_steps: string[];
  escalation: string;
  source_ticket_ids: string[];
  status: DraftStatus;
  reviewer: string | null;
  reason_code: string | null;
  note: string | null;
  decided_at: string | null;
  created_at: string;
}

export type DraftFields = Pick<KBDraft, "title" | "symptoms" | "root_cause" | "resolution_steps" | "escalation">;

export const DRAFT_REJECT_REASONS = [
  { value: "not_a_known_issue", label: "Not a known issue" },
  { value: "duplicate", label: "An article already covers it" },
  { value: "wrong", label: "The draft is wrong" },
  { value: "other", label: "Other" },
] as const;

export interface KBDraftReview extends Partial<DraftFields> {
  action: "approved" | "edited" | "rejected";
  reviewer: string;
  reason_code?: (typeof DRAFT_REJECT_REASONS)[number]["value"];
  note?: string;
}

export interface ProblemCandidate {
  id: number;
  application: string | null;
  issue_key: string; // article:KB-PAY-002 or draft:12
  ticket_ids: string[];
  cases: number;
  first_closed: string;
  last_closed: string;
  status: "open" | "accepted" | "dismissed";
  decided_by: string | null;
  decided_at: string | null;
  note: string | null;
}

export interface AppCoverage {
  application: string;
  articles: number;
  cases: number;
  matched: number;
  gap: number;
  uncertain: number;
  outside_kb: number;
  drafts_waiting: number;
  covered_share: number;
  unused_articles: string[];
}

export interface KnowledgeRunResult {
  evaluated: number;
  skipped: number;
  model_errors: number;
  by_status: Record<string, number>;
  drafts: Record<string, number>;
  open_problems: number;
}

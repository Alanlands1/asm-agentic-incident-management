export interface Storm {
  id: number;
  application: string | null;
  issue_key: string;
  main_ticket_id: string;
  people: number;
  ticket_count: number;
  opened_at: string;
  last_ticket_at: string;
  status: "open" | "closed" | "declared";
  declared_by: string | null;
  declared_at: string | null;
  ticket_ids: string[];
}

export interface FirstMessageSent {
  id: number;
  ticket_id: string;
  storm_id: number | null;
  text: string;
  sent_by: string;
  sent_at: string;
}

export interface AttentionItem {
  ticket_id: string;
  summary: string;
  application: string | null;
  priority: number;
  priority_from: "reviewed" | "recommended";
  opened_at: string;
  due_at: string;
  used_percent: number;
  state: "ok" | "watch" | "breach_likely" | "breached";
  minutes_left: number;
  storm_id: number | null;
  first_message: { text: string; send_by: string; minutes_left: number };
  last_sent: FirstMessageSent | null;
  /** The ticket came from Jira and writing to Jira is switched on. */
  can_post_to_jira: boolean;
}

export interface Attention {
  storms: Storm[];
  p1_p2: AttentionItem[];
  count: number;
}

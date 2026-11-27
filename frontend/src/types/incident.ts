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
  ticket_summaries?: Record<string, string>;
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
  /** The system sends this ticket's stakeholder updates by itself. Missing until the backend is restarted: treat as false. */
  auto_send?: boolean;
  /** When the next update is due (last sent time plus the update interval); null when nothing has been sent yet. */
  next_update_at?: string | null;
}

export interface Attention {
  storms: Storm[];
  p1_p2: AttentionItem[];
  count: number;
}

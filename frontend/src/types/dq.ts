export type ApplyToScope = "existing" | "new" | "both";
export type DQRunType = "manual" | "scheduled";
export type DQRunStatus = "completed" | "failed" | "reverted";
export type TicketSource = "servicenow" | "jira" | "mailbox";

export interface TicketSourceOption {
  value: TicketSource;
  label: string;
}

export type DQOperator =
  | "equals"
  | "not_equals"
  | "contains"
  | "not_contains"
  | "starts_with"
  | "regex"
  | "is_empty"
  | "is_not_empty"
  | "length_lt"
  | "length_gt";

export interface DQRule {
  id: number;
  name: string;
  description?: string | null;
  field: string;
  operator: DQOperator;
  value?: string | null;
  apply_to: ApplyToScope;
  source?: TicketSource | string | null;
  service?: string | null;
  is_enabled: boolean;
  created_at: string;
  updated_at?: string;
  deleted_at?: string | null;
}

export interface DQRuleCreateInput {
  name: string;
  description?: string | null;
  field: string;
  operator: DQOperator;
  value?: string | null;
  apply_to: ApplyToScope;
  source?: TicketSource | string | null;
  service?: string | null;
  is_enabled?: boolean;
}

export interface DQRuleUpdateInput {
  name?: string;
  description?: string | null;
  field?: string;
  operator?: DQOperator;
  value?: string | null;
  apply_to?: ApplyToScope;
  source?: TicketSource | string | null;
  service?: string | null;
  is_enabled?: boolean;
}

export interface DQRun {
  id: number;
  trigger: DQRunType;
  scope: ApplyToScope;
  tickets_evaluated: number;
  tickets_flagged: number;
  status: DQRunStatus;
  rules_snapshot: Record<string, unknown>[];
  started_at: string;
  finished_at?: string | null;
  reverted_at?: string | null;
}

export interface DQRunMatchTicket {
  ticket_id: string;
  rule_id: number;
  rule_name: string;
  ticket_short_description?: string | null;
  ticket_service?: string | null;
  ticket_priority?: string | null;
}

export interface DQRunDetail extends DQRun {
  matches: DQRunMatchTicket[];
}

export interface DQRunCreateInput {
  scope: ApplyToScope;
  source?: string | null;
  trigger?: DQRunType;
}

export interface DQRuleFilterParams {
  source?: string;
  service?: string;
  is_enabled?: boolean;
}

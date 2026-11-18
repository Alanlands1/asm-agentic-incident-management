export interface ServiceNowTicket {
  ticket_id: string;
  caller?: string | null;
  short_description?: string | null;
  description?: string | null;
  priority?: string | null;
  assignment_group?: string | null;
  service?: string | null;
  resolution_notes?: string | null;
  opened_at?: string | null;
  closed_at?: string | null;
  dq_flag: boolean;
  dq_reason?: string | null;
  created_at?: string;
}

export interface ServiceNowTicketListResponse {
  total: number;
  items: ServiceNowTicket[];
}

export interface ServiceNowTicketFilterParams {
  dq_flag?: boolean;
  dq_reason?: string;
  service?: string;
  priority?: string;
  caller?: string;
  is_unresolved?: boolean;
  limit?: number;
  offset?: number;
}

import { apiClient } from "@/lib/api-client";
import {
  ServiceNowTicket,
  ServiceNowTicketListResponse,
  ServiceNowTicketFilterParams,
} from "@/types/servicenow";

export const ticketService = {
  async getTickets(params?: ServiceNowTicketFilterParams): Promise<ServiceNowTicketListResponse> {
    const q = new URLSearchParams();
    if (params?.dq_flag !== undefined) q.append("dq_flag", String(params.dq_flag));
    if (params?.dq_reason) q.append("dq_reason", params.dq_reason);
    if (params?.service) q.append("service", params.service);
    if (params?.priority) q.append("priority", params.priority);
    if (params?.caller) q.append("caller", params.caller);
    if (params?.is_unresolved !== undefined) q.append("is_unresolved", String(params.is_unresolved));
    if (params?.limit !== undefined) q.append("limit", String(params.limit));
    if (params?.offset !== undefined) q.append("offset", String(params.offset));

    const qs = q.toString();
    return apiClient<ServiceNowTicketListResponse>(`/servicenow/tickets${qs ? `?${qs}` : ""}`);
  },

  async getTicket(ticketId: string): Promise<ServiceNowTicket> {
    return apiClient<ServiceNowTicket>(`/servicenow/tickets/${ticketId}`);
  },
};

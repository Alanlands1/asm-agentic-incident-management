import { apiClient } from "@/lib/api-client";
import { Attention, FirstMessageSent, Storm } from "@/types/incident";

export const incidentService = {
  getAttention: () => apiClient<Attention>("/incidents/attention"),
  /** With `postToJira` the text is added to the Jira issue as a comment before it is recorded as sent. */
  markSent: (ticketId: string, text: string, sentBy: string, postToJira = false) =>
    apiClient<FirstMessageSent>(`/incidents/tickets/${encodeURIComponent(ticketId)}/first-message`, {
      method: "POST",
      body: JSON.stringify({ text, sent_by: sentBy, post_to_jira: postToJira }),
    }),
  declare: (stormId: number, declaredBy: string) =>
    apiClient<Storm>(`/storms/${stormId}/declare`, { method: "POST", body: JSON.stringify({ declared_by: declaredBy }) }),
};

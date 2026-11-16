import { apiClient } from "@/lib/api-client";
import { AgentCheckResult, AgentRunResult, AgentSlug, ClosureQueueItem, PipelineTicket, ReviewInput, ReviewQueueItem } from "@/types/pipeline";

const id = encodeURIComponent;

export const pipelineService = {
  getTicket: (ticketId: string) => apiClient<PipelineTicket>(`/tickets/${id(ticketId)}`),
  reviewQueue: (limit = 200) => apiClient<ReviewQueueItem[]>(`/triage/review-queue?limit=${limit}`),
  review: (ticketId: string, body: ReviewInput) =>
    apiClient(`/triage/tickets/${id(ticketId)}/review`, { method: "POST", body: JSON.stringify(body) }),
  /** Adds the reply to the Jira issue as a comment and keeps a copy on the ticket. */
  replyInJira: (ticketId: string, author: string, body: string) =>
    apiClient(`/tickets/${id(ticketId)}/comments`, {
      method: "POST",
      body: JSON.stringify({ author_email: author, body, post_to_jira: true }),
    }),
  /** Comments what the agents decided on the Jira issue and keeps a copy on the ticket. */
  sendToJira: (ticketId: string, author: string) =>
    apiClient(`/tickets/${id(ticketId)}/agent-summary`, { method: "POST", body: JSON.stringify({ author_email: author }) }),
  /** Data Quality on one ticket (Triage follows if it passes) or Triage alone; again if they ran before. */
  runAgents: (ticketId: string, agent: "data_quality" | "triage") =>
    apiClient(`/tickets/${id(ticketId)}/run-agents`, { method: "POST", body: JSON.stringify({ agent }) }),
  /** Keeps a person's note to the agents on the ticket; empty text removes it. */
  setGuidance: (ticketId: string, text: string) =>
    apiClient(`/tickets/${id(ticketId)}/guidance`, { method: "PUT", body: JSON.stringify({ text }) }),
  rate: (ticketId: string, body: { agent_run_id: number; stars: number; reason: string; reviewer: string }) =>
    apiClient(`/tickets/${id(ticketId)}/feedback`, { method: "POST", body: JSON.stringify(body) }),
  run: (agent: AgentSlug) => apiClient<AgentRunResult>(`/${agent}/run`, { method: "POST" }),
  check: (agent: AgentSlug, ticketId: string) =>
    apiClient<AgentCheckResult>(`/${agent}/tickets/${id(ticketId)}/check`, { method: "POST" }),
  closureQueue: () => apiClient<ClosureQueueItem[]>("/closure/queue"),
};

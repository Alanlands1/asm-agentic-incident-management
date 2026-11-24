import { apiClient } from "@/lib/api-client";
import { AgentCheckResult, AgentRun, AgentRunResult, AgentSlug, ClosureQueueItem, Outcome, PipelineTicket, ReviewInput, ReviewQueueItem, TicketListItem } from "@/types/pipeline";

const id = encodeURIComponent;

export const pipelineService = {
  getTicket: (ticketId: string) => apiClient<PipelineTicket>(`/tickets/${id(ticketId)}`),
  /** Tickets at one stage of the agents' pipeline, e.g. in_review. */
  listByStage: (stage: string, limit = 200) =>
    apiClient<{ total: number; items: TicketListItem[] }>(`/tickets?pipeline_status=${id(stage)}&limit=${limit}`),
  reviewQueue: (limit = 200) => apiClient<ReviewQueueItem[]>(`/triage/review-queue?limit=${limit}`),
  review: (ticketId: string, body: ReviewInput) =>
    apiClient(`/triage/tickets/${id(ticketId)}/review`, { method: "POST", body: JSON.stringify(body) }),
  /** Keeps an update on the ticket; with postToJira it is also added to the Jira issue as a comment. */
  addComment: (ticketId: string, author: string, body: string, postToJira: boolean) =>
    apiClient(`/tickets/${id(ticketId)}/comments`, {
      method: "POST",
      body: JSON.stringify({ author_email: author, body, post_to_jira: postToJira }),
    }),
  /** Adds the reply to the Jira issue as a comment and keeps a copy on the ticket. */
  replyInJira: (ticketId: string, author: string, body: string) => pipelineService.addComment(ticketId, author, body, true),
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
  /** A decision on the latest close-notes check: take the agent's draft, or keep the person's own version. */
  closureReview: (ticketId: string, body: { action: "accepted" | "edited"; reviewer: string; final_text?: string }) =>
    apiClient(`/closure/tickets/${id(ticketId)}/review`, { method: "POST", body: JSON.stringify(body) }),
  /** The engineer's answer on the latest suggested fix: worked opens the closure note, wrong asks for another fix. */
  fixOutcome: (ticketId: string, body: { agent_run_id: number; outcome: Outcome; note?: string; reviewer: string }) =>
    apiClient(`/tickets/${id(ticketId)}/fix-outcome`, { method: "POST", body: JSON.stringify(body) }),
  /** Keeps the closure note in the console; Closure Quality checks it again. */
  saveClosureNote: (ticketId: string, text: string) =>
    apiClient(`/tickets/${id(ticketId)}/closure-note`, { method: "PUT", body: JSON.stringify({ text }) }),
  /** A draft email telling the requester the ticket is resolved, from the saved closure note. Nothing is sent. */
  draftEmail: (ticketId: string) =>
    apiClient<{ subject: string; body: string }>(`/closure/tickets/${id(ticketId)}/email`, { method: "POST" }),
  /** Starts the ticket's chat with the AI assistant afresh; the turns stay in the activity log. */
  clearChat: (ticketId: string) => apiClient(`/tickets/${id(ticketId)}/chat`, { method: "DELETE" }),
  /** One turn with the AI assistant about the fix; returns the stored turn. */
  chat: (ticketId: string, body: { message: string; author: string }) =>
    apiClient<AgentRun>(`/tickets/${id(ticketId)}/chat`, { method: "POST", body: JSON.stringify(body) }),
  /** Makes the assistant's proposed fix the ticket's suggested fix. */
  useChatFix: (ticketId: string, body: { run_id: number; reviewer: string }) =>
    apiClient(`/tickets/${id(ticketId)}/chat/use`, { method: "POST", body: JSON.stringify(body) }),
  /** Hands the checked closure note to the lead (when LEAD_REVIEW asks for it). */
  submitReview: (ticketId: string, reviewer: string) =>
    apiClient(`/tickets/${id(ticketId)}/submit-review`, { method: "POST", body: JSON.stringify({ reviewer }) }),
  /** The lead approves the closure note, or sends it back with what to change. */
  leadReview: (ticketId: string, body: { action: "approved" | "sent_back"; note?: string; reviewer: string }) =>
    apiClient(`/tickets/${id(ticketId)}/lead-review`, { method: "POST", body: JSON.stringify(body) }),
  /** Everyone a ticket can go to: who Jira lets be assigned and who has held a ticket; `member` is on the team. */
  roster: () => apiClient<{ name: string; in_jira: boolean | null; held: boolean; member: boolean }[]>("/personas/roster"),
  /** Each engineer's state now: on shift, off shift, or on leave with its last day. */
  availability: () => apiClient<Record<string, { state: "on_shift" | "off_shift" | "on_leave"; until: string | null }>>("/personas/availability"),
  /** An engineer for each unassigned open ticket, with the reason; a ticket left out has no one under the limit. */
  suggestions: () => apiClient<{ limit: number; suggestions: { id: string; name: string; reason: string }[] }>("/personas/suggestions"),
  /** The lead gives the ticket to an engineer (null: nobody); a Jira issue is assigned in Jira too. */
  assign: (ticketId: string, assignee: string | null, by: string) =>
    apiClient(`/tickets/${id(ticketId)}/assign`, { method: "POST", body: JSON.stringify({ assignee, by }) }),
  /** Posts the closure note on the Jira issue and moves the issue to done. */
  closeInJira: (ticketId: string, author: string) =>
    apiClient(`/tickets/${id(ticketId)}/close`, { method: "POST", body: JSON.stringify({ author_email: author }) }),
};

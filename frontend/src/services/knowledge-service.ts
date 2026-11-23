import { apiClient, getApiBase } from "@/lib/api-client";
import { AppCoverage, DraftStatus, KBDraft, KBDraftReview, KnowledgeRunResult, ProblemCandidate } from "@/types/knowledge";

export const knowledgeService = {
  run: () => apiClient<KnowledgeRunResult>("/knowledge/run", { method: "POST" }),
  drafts: (status: DraftStatus) => apiClient<KBDraft[]>(`/knowledge/drafts?status=${status}`),
  review: (id: number, body: KBDraftReview) =>
    apiClient<KBDraft>(`/knowledge/drafts/${id}/review`, { method: "POST", body: JSON.stringify(body) }),
  publish: (id: number) => apiClient<KBDraft>(`/knowledge/drafts/${id}/publish`, { method: "POST" }),
  exportUrl: (id: number) => `${getApiBase()}/knowledge/drafts/${id}/export`,
  problems: () => apiClient<ProblemCandidate[]>("/knowledge/problems?status=open"),
  decide: (id: number, action: "accepted" | "dismissed", decided_by: string) =>
    apiClient<ProblemCandidate>(`/knowledge/problems/${id}/decision`, { method: "POST", body: JSON.stringify({ action, decided_by }) }),
  coverage: () => apiClient<AppCoverage[]>("/knowledge/coverage"),
};

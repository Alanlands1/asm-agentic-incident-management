import { apiClient } from "@/lib/api-client";
import {
  DQRule,
  DQRuleCreateInput,
  DQRuleUpdateInput,
  DQRuleFilterParams,
  DQRun,
  DQRunCreateInput,
  DQRunDetail,
  DQRunMatchTicket,
} from "@/types/dq";

export const dqService = {
  async getRules(params?: DQRuleFilterParams): Promise<DQRule[]> {
    const q = new URLSearchParams();
    if (params?.source) q.append("source", params.source);
    if (params?.service) q.append("service", params.service);
    if (params?.is_enabled !== undefined) q.append("is_enabled", String(params.is_enabled));
    const qs = q.toString();
    const res = await apiClient<{ total: number; items: DQRule[] } | DQRule[]>(
      `/dq/rules${qs ? `?${qs}` : ""}`
    );
    return Array.isArray(res) ? res : res.items || [];
  },

  async createRule(payload: DQRuleCreateInput): Promise<DQRule> {
    return apiClient<DQRule>("/dq/rules", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async updateRule(id: number, payload: DQRuleUpdateInput): Promise<DQRule> {
    return apiClient<DQRule>(`/dq/rules/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  async toggleRule(id: number, isEnabled: boolean): Promise<DQRule> {
    return apiClient<DQRule>(`/dq/rules/${id}/toggle?is_enabled=${isEnabled}`, {
      method: "PATCH",
    });
  },

  async deleteRule(id: number): Promise<DQRule> {
    return apiClient<DQRule>(`/dq/rules/${id}`, {
      method: "DELETE",
    });
  },

  async getRuns(limit = 20, offset = 0): Promise<DQRun[]> {
    const res = await apiClient<{ total: number; items: DQRun[] } | DQRun[]>(
      `/dq/runs?limit=${limit}&offset=${offset}`
    );
    return Array.isArray(res) ? res : res.items || [];
  },

  async getSources(): Promise<{ code: string; name: string; description?: string }[]> {
    return apiClient<{ code: string; name: string; description?: string }[]>("/dq/sources");
  },

  async createRun(payload: DQRunCreateInput): Promise<DQRun> {
    return apiClient<DQRun>("/dq/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async getRunDetail(id: number): Promise<DQRunDetail> {
    // The run and its flagged tickets are separate endpoints.
    const [run, matches] = await Promise.all([
      apiClient<DQRun>(`/dq/runs/${id}`),
      apiClient<{ items: DQRunMatchTicket[] }>(`/dq/runs/${id}/matches?limit=500`),
    ]);
    return { ...run, matches: matches.items };
  },

  async revertRun(id: number): Promise<DQRun> {
    return apiClient<DQRun>(`/dq/runs/${id}/revert`, {
      method: "POST",
    });
  },
};
